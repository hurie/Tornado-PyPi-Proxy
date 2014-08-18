"""
Created on Aug 17, 2014

@author: Azhar
"""
from tornado.escape import utf8
from tornado.httputil import HTTPHeaders, _parse_header
from tornado.log import app_log
from tornado.web import stream_request_body, RequestHandler, HTTPError


@stream_request_body
class StreamingFormDataHandler(RequestHandler):
    HANDLE_PREFIX = 'on'
    HANDLE_BEGIN_SUFFIX = 'begin'
    HANDLE_DATA_SUFFIX = 'data'
    HANDLE_END_SUFFIX = 'end'

    def prepare(self):
        self._boundary = None
        self._boundary_length = None
        self._disp_header = None
        self._disp_params = None
        self._disp_name = None
        self._disp_buffer = None
        self._buffer = None

        content_type = self.request.headers.get('content-type', '')
        if not content_type.startswith('multipart/form-data'):
            raise HTTPError(400)

        fields = content_type.split(';')
        for field in fields:
            k, sep, v = field.strip().partition('=')
            if k == 'boundary' and v:
                if v.startswith('"') and v.endswith('"'):
                    v = v[1:-1]
                self._boundary = b'--' + utf8(v)
                self._boundary_length = len(self._boundary) + 2
                break

        if self._boundary is None:
            raise HTTPError(400)

        app_log.debug('boundary: %s', self._boundary)

    def execute_handle(self, suffix, *args, **kwargs):
        if self._disp_name is None:
            return False

        handler = getattr(self, '_'.join([self.HANDLE_PREFIX, self._disp_name, suffix]), None)
        if handler:
            handler(*args, **kwargs)
            return True
        return False

    def data_received(self, data):
        if self._buffer is not None:
            data = self._buffer + data
            self._buffer = None

        boundary = data.find(self._boundary)
        if boundary != 0:
            # boundary not at the begining
            value = data if boundary == -1 else data[:boundary - 2]
            if not self.execute_handle(self.HANDLE_DATA_SUFFIX, value):
                self._disp_buffer += value

            if boundary == -1:
                # boundary not found, streaming in progress
                return
            # boundary found, terminate current disposition
            self.execute_handle(self.HANDLE_END_SUFFIX)

        # process all disposition found in current stream
        while boundary != -1:
            app_log.debug('processing boundary')
            data = data[boundary:]

            # find next boundary
            boundary = data.find(self._boundary, self._boundary_length)

            eoh = data.find(b'\r\n\r\n')
            if eoh == -1:
                if boundary == -1:
                    # header and boundary not found, stream probably cut in the midle of header
                    self._buffer = data
                    break
                # disposition not found because header not found
                app_log.debug('invalid disposition header')
                continue

            # process header
            data_header = data[self._boundary_length:eoh]

            app_log.debug('header data: %r', data_header)
            self._disp_header = HTTPHeaders.parse(data_header.decode('utf-8'))
            disp_header = self._disp_header.get('Content-Disposition', '')

            disposition, self._disp_params = _parse_header(disp_header)
            if disposition != 'form-data':
                app_log.warning('invalid multipart/form-data')
                continue

            self._disp_name = self._disp_params.get('name')
            if self._disp_name is None:
                app_log.warning('multipart/form-data value missing name')
                continue
            app_log.debug('disposition name %s', self._disp_name)

            # get disposition value and execute begin handler
            if boundary == -1:
                value = data[eoh + 4:]
            else:
                value = data[eoh + 4:boundary - 2]
            self._disp_buffer = value
            self.execute_handle(self.HANDLE_BEGIN_SUFFIX, value)

            if boundary != -1:
                # next boundary found, execute end handler
                self.execute_handle(self.HANDLE_END_SUFFIX)

    def post(self):
        return
