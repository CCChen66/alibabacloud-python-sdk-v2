# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import time
import copy

from alibabacloud.vendored.six.moves.urllib.request import pathname2url
from alibabacloud.vendored.six import iteritems
from alibabacloud.compat import urlencode
from alibabacloud.exceptions import NoCredentialsException
from alibabacloud.signer.algorithm import ShaHmac1 as mac1
from alibabacloud.utils import format_type as FormatType, parameter_helper as helper
from alibabacloud.utils.parameter_helper import md5_sum

FORMAT_ISO_8601 = "%Y-%m-%dT%H:%M:%SZ"
HEADER_SEPARATOR = "\n"


# this function will append the necessary parameters for signers process.
# parameters: the orignal parameters
# signers: sha_hmac1 or sha_hmac256
# accessKeyId: this is aliyun_access_key_id
# format: XML or JSON
# input parameters is headers


class ROASigner:

    def __init__(self, credentials, api_request, region_id, version, signer=None):
        self.credentials = credentials
        self.request = api_request
        self.region_id = region_id
        self.version = version

        if signer is not None:
            self.signer = signer()
        else:
            self.signer = mac1()

        self._headers = self._prepare_headers()
        self._uri = self._replace_occupied_parameters()

    def _prepare_headers(self):
        if self.credentials is None:
            raise NoCredentialsException()
        headers = copy.deepcopy(self.request._headers)
        headers['x-acs-version'] = self.version
        headers['x-acs-region-id'] = str(self.region_id)
        if self.request._content is not None:
            headers['Content-MD5'] = md5_sum(self.request._content)

        if getattr(self.credentials, 'security_token') is not None:
            headers['x-acs-security-token'] = self.credentials.security_token

        if getattr(self.credentials, 'bearer_token') is not None:
            headers['x-acs-bearer-token'] = self.credentials.bearer_token
        return headers

    def _refresh_sign_parameters(self):
        parameters = self._headers
        if parameters is None or not isinstance(parameters, dict):
            parameters = dict()
        parameters["Date"] = helper.get_rfc_2616_date()
        parameters["Accept"] = FormatType.map_format_to_accept('JSON')
        parameters["x-acs-signature-method"] = self.signer.signer_name
        parameters["x-acs-signature-version"] = self.signer.signer_version
        return parameters

    def _replace_occupied_parameters(self):
        uri_pattern = copy.deepcopy(self.request.uri_pattern)
        paths = self.request.path_params
        result = uri_pattern
        if paths:
            for (key, value) in iteritems(paths):
                target = "[" + key + "]"
                result = result.replace(target, value)
        return result

    @property
    def signature(self):
        headers = self._refresh_sign_parameters()
        sign_to_string = ''
        interesting_headers = ['Accept', 'Content-MD5', 'Content-Type', 'Date']
        sign_to_string += self.request.method.upper()
        sign_to_string += "\n"
        for ih in interesting_headers:
            if headers.get(ih) is not None:
                sign_to_string += headers[ih]
            sign_to_string += "\n"
        sign_to_string += self._build_canonical_headers(headers, "x-acs-")
        sign_to_string += self._build_canonical_resource(self._uri, self.request._query_params)
        return sign_to_string

    # change the give headerBegin to the lower() which in the headers
    # and change it to key.lower():value
    @staticmethod
    def _build_canonical_headers(headers, header_begin):
        """
        alibabacloud headers
        :param headers:
        :param header_begin:
        :return:
        """
        result = ""
        unsort_map = dict()
        for (key, value) in iteritems(headers):
            if key.lower().find(header_begin) >= 0:
                unsort_map[key.lower()] = value
        sort_map = sorted(iteritems(unsort_map), key=lambda d: d[0])
        for (key, value) in sort_map:
            result += key + ":" + value
            result += "\n"
        return result

    @staticmethod
    def _build_canonical_resource(uri, queries):
        """
        resource and params
        :param uri:
        :param queries:
        :return:
        """
        uri_parts = uri.rsplit("?", 1)
        if len(uri_parts) > 1 and uri_parts[1] is not None:
            queries[uri_parts[1]] = None
        query_builder = uri_parts[0]
        sorted_map = sorted(iteritems(queries), key=lambda queries: queries[0])
        if len(sorted_map) > 0:
            query_builder += "?"
        for (k, v) in sorted_map:
            query_builder += k
            if v is not None:
                query_builder += "="
                query_builder += str(v)
            query_builder += "&"
        if query_builder.endswith("&"):
            query_builder = query_builder[0:(len(query_builder) - 1)]
        return query_builder

    @property
    def headers(self):
        headers = self._headers
        signature = self.signer.sign_string(self.signature, self.credentials.access_key_secret)
        headers['Authorization'] = "acs %s:%s" % (self.credentials.access_key_id, signature)
        return headers

    @property
    def params(self):
        param = ""
        param += self._uri
        if not param.endswith("?"):
            param += "?"
        param += urlencode(self.request._query_params)
        if param.endswith("?"):
            param = param[0:(len(param) - 1)]
        return param


class RPCSigner:
    def __init__(self, credentials, api_request, region_id, version, signer=None):
        self.credentials = credentials
        self.request = api_request
        self.region_id = region_id
        self.version = version
        if signer is None:
            self.signer = mac1()
        else:
            self.signer = signer()

        self.parameters = self._canonicalized_query_string()

    @property
    def signature(self):
        parameters = self.parameters
        # rpc body_params query_params level
        parameters.update(self.request._body_params)
        if getattr(self.credentials, 'security_token') is not None:
            parameters['SecurityToken'] = self.credentials.security_token

        if getattr(self.credentials, 'bearer_token') is not None:
            parameters['BearerToken'] = self.credentials.bearer_token
        signature = self._calc_signature(self.request.method, parameters)
        return signature

    @property
    def params(self):
        parameters = self.parameters
        signature = self.signer.sign_string(self.signature,
                                            str(self.credentials.access_key_secret) + '&')
        parameters['Signature'] = signature
        params = '?' + urlencode(parameters)
        return params

    @property
    def headers(self):
        return self.request._headers

    @staticmethod
    def _pop_standard_urlencode(query):
        ret = query.replace('+', '%20')
        ret = ret.replace('*', '%2A')
        ret = ret.replace('%7E', '~')
        return ret

    def _calc_signature(self, method, params):
        sorted_parameters = sorted(iteritems(params), key=lambda queries: queries[0])
        sorted_query_string = self._pop_standard_urlencode(urlencode(sorted_parameters))
        canonicalized_query_string = self._pop_standard_urlencode(pathname2url(sorted_query_string))
        string_to_sign = method + "&%2F&" + canonicalized_query_string
        return string_to_sign

    def _canonicalized_query_string(self):
        if self.credentials is None:
            raise NoCredentialsException()
        parameters = copy.deepcopy(self.request._query_params)
        # TODO version :client level
        parameters['Version'] = self.version
        parameters['Action'] = self.request.action_name
        # parameters['Format'] = self.request.accept_format
        parameters['Format'] = "JSON"
        parameters["Timestamp"] = time.strftime(FORMAT_ISO_8601, time.gmtime())
        parameters["SignatureMethod"] = self.signer.signer_name
        # self.signer.si
        parameters["SignatureType"] = self.signer.signer_type
        parameters["SignatureVersion"] = self.signer.signer_version
        parameters["SignatureNonce"] = helper.get_uuid()
        if getattr(self.credentials, 'access_key_id') is not None:
            parameters["AccessKeyId"] = self.credentials.access_key_id
        return parameters


SIGNER_MAP = {
    'RPC': RPCSigner,
    'ROA': ROASigner
}
