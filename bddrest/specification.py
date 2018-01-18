import re
import json
import io
from urllib.parse import urlencode

import yaml
from webtest import TestApp

from .helpers import normalize_headers, normalize_query_string


CONTENT_TYPE_PATTERN = re.compile('(\w+/\w+)(?:;\s?charset=(.+))?')
URL_PARAMETER_VALUE_PATTERN = '[\w\d_-]+'
URL_PARAMETER_PATTERN = re.compile(f'/(?P<key>\w+):\s?(?P<value>{URL_PARAMETER_VALUE_PATTERN})')


class Response:
    content_type = None
    encoding = None

    def __init__(self, status, headers, body=None):
        self.status = status
        self.headers = normalize_headers(headers)
        self.body = body.encode() if body is not None and not isinstance(body, bytes) else body

        if ' ' in status:
            parts = status.split(' ')
            self.status_code, self.status_text = int(parts[0]), ' '.join(parts[1:])
        else:
            self.status_code = int(status)

        for k, v in self.headers:
            if k == 'Content-Type':
                match = CONTENT_TYPE_PATTERN.match(v)
                if match:
                    self.content_type, self.encoding = match.groups()
                break

    @property
    def text(self):
        return self.body.decode()

    @property
    def json(self):
        return json.loads(self.body)

    def to_dict(self):
        result = dict(
            status=self.status
        )
        if self.headers:
            result['headers'] = [': '.join(h) for h in self.headers]

        if self.body:
            result['body'] = self.body.decode()
        return result


class Call:
    _response: Response = None

    def __init__(self, title: str, url='/', verb='GET', url_parameters: dict = None,
                 form: dict = None, content_type: str = None, headers: list = None, as_: str = None, query: dict = None,
                 description: str = None, extra_environ: dict = None, response=None):
        self.title = title
        self.response = response
        self.description = description
        self.extra_environ = extra_environ

        self.url, self.url_parameters = self.extract_url_parameters(url)
        if url_parameters:
            self.url_parameters.update(url_parameters)
        self.verb = verb
        self.form = form
        self.content_type = content_type
        self.headers = normalize_headers(headers)
        self.as_ = as_
        self.query = normalize_query_string(query)

    @property
    def response(self) -> Response:
        return self._response

    @response.setter
    def response(self, v):
        self._response = Response(**v) if v and not isinstance(v, Response) else v

    def to_dict(self):
        result = dict(
            title=self.title,
            url=self.url,
            verb=self.verb,
        )
        if self.url_parameters is not None:
            result['url_parameters'] = self.url_parameters

        if self.form is not None:
            result['form'] = self.form

        if self.headers is not None:
            result['headers'] = [': '.join(h) for h in self.headers]

        if self.as_ is not None:
            result['as_'] = self.as_

        if self.query is not None:
            result['query'] = self.query

        if self.description is not None:
            result['description'] = self.description

        if self.response is not None:
            result['response'] = self.response.to_dict()

        return result

    @staticmethod
    def extract_url_parameters(url):
        url_parameters = {}
        if URL_PARAMETER_PATTERN.search(url):
            for k, v in URL_PARAMETER_PATTERN.findall(url):
                url_parameters[k] = v
                url = re.sub(f'{k}:\s?{URL_PARAMETER_VALUE_PATTERN}', f':{k}', url)
        return url, url_parameters

    def invoke(self, application):
        url = f'{self.url}?{urlencode(self.query)}' if self.query else self.url

        headers = self.headers or []
        if self.content_type:
            headers = [h for h in headers if h[0].lower() != 'content-type']
            headers.append(('Content-Type', self.content_type))

        request_params = dict(
            expect_errors=True,
            extra_environ=self.extra_environ,
            headers=headers,
            # Commented for future usages by pylover
            # upload_files=upload_files,
        )
        if self.form:
            request_params['params'] = self.form

        # noinspection PyProtectedMember
        response = TestApp(application)._gen_request(self.verb, url, **request_params)
        return Response(response.status, [(k, v) for k, v in response.headers.items()], body=response.body)


class OverriddenCall(Call):
    def __init__(self, base_call: Call, title: str, description=None, response=None, url_parameters=None, **diff):
        self.base_call = base_call
        if 'url' in diff:
            diff['url'], diff['url_parameters'] = self.extract_url_parameters(diff['url'])
        if url_parameters:
            diff['url_parameters'].update(url_parameters)
        self.diff = diff

        data = {k: v for k, v in base_call.to_dict().items() if k not in ('response', 'title', 'description')}
        data.update(diff)
        super().__init__(title, description=description, response=response, **data)

    def to_dict(self):
        result = dict(title=self.title)
        result.update(self.diff)

        if self.description is not None:
            result['description'] = self.description

        if self.response is not None:
            result['response'] = self.response.to_dict()

        return result


class Story:
    def __init__(self, base_call, calls=None):
        self.base_call = base_call
        self.calls = calls or []

    def to_dict(self):
        return dict(
            base_call=self.base_call.to_dict(),
            calls=[c.to_dict() for c in self.calls]
        )

    @classmethod
    def from_dict(cls, data):
        base_call = Call(**data['base_call'])
        return cls(
            base_call,
            calls=[OverriddenCall(base_call, **d) for d in data['calls']] if data.get('calls') else None
        )

    def dump(self, file):
        data = self.to_dict()
        yaml.dump(data, file, default_style=False, default_flow_style=False)

    def dumps(self):
        file = io.StringIO()
        self.dump(file)
        return file.getvalue()
