from __future__ import absolute_import
import logging
import random
import time

import requests

from .exceptions import NotFound

logger = logging.getLogger(__name__)

requests_logger = logging.getLogger('requests.packages.urllib3')
requests_logger.setLevel(logging.WARNING)


class ItemSet(list):
    def __init__(self, *args, **kwargs):
        self._item_class = None
        return super(ItemSet, self).__init__(*args, **kwargs)

    def find_all(self, **kwargs):
        filtered = ItemSet(
            x for x in self
            if all(getattr(x, k) == v for k, v in kwargs.items()))
        filtered._item_class = self._item_class
        return filtered

    def find(self, **kwargs):
        items = self.find_all(**kwargs)
        if items:
            return items[0]
        else:
            raise NotFound(self._item_class, **kwargs)


class Collection(object):

    _list_url = 'get_{name}s'
    _add_url = 'add_{name}'

    def __init__(self, item_class=None, parent_id=None, **kwargs):
        self._item_class = item_class
        self._handler = self._item_class._handler
        self._pagination_handler = self._item_class._pagination_handler
        self.parent_id = parent_id
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __call__(self, id=None):
        name = self._item_class._api_name()
        if id is None:
            items = self._list(name)
            if 'error' in items:
                raise Exception(items)
            items = ItemSet(self._to_object(x) for x in items)
            items._item_class = self._item_class
            return items

        else:
            return self._item_class.get(id)

    def __repr__(self):
        return '<Collection of {}>'.format(self._item_class.__name__)

    def _to_object(self, data):
        return self._item_class(**data)

    def _list(self, name, params=None):
        params = params or {}
        url = self._list_url.format(name=name)
        if self.parent_id is not None:
            url += '/{}'.format(self.parent_id)
        return self._pagination_handler(url=url, name=name, params=params)

    def _add(self, name, data, **kwargs):
        url = self._add_url.format(name=name)
        if self.parent_id is not None:
            url += '/{}'.format(self.parent_id)
        return self._handler('POST', url, json=data, **kwargs)

    def find_all(self, **kwargs):
        return self().find_all(**kwargs)

    def find(self, **kwargs):
        # if plan is searched perform an additional GET request to API
        # in order to return full its data including 'entries' field
        # see http://docs.gurock.com/testrail-api2/reference-plans#get_plans
        if self._item_class is Plan:
            return self.get(self().find(**kwargs).id)
        return self().find(**kwargs)

    def get(self, id):
        return self._item_class.get(id)

    def add(self, **kwargs):
        item = self._to_object(kwargs)
        result = self._add(item._api_name(), item.data)
        return self._to_object(result)

    def list(self):
        name = self._item_class._api_name()
        return ItemSet([self._item_class(**i) for i in self._list(name=name)])


class Item(object):
    _get_url = 'get_{name}/{id}'
    _update_url = 'update_{name}/{id}'
    _handler = None
    _repr_field = 'name'

    def __init__(self, id=None, **kwargs):
        self.id = id
        self._data = kwargs

    @classmethod
    def _api_name(cls):
        return cls.__name__.lower()

    @classmethod
    def _pagination_handler(cls, url, name, params=None):
        """
        :param name: Name of the key in the response (single),
                     which contains the current portion of list of the objects
        """
        key_name = f"{name}s"
        params = params or {}
        # TODO(ddmitriev): remove 'beta' header after 26 Feb 2021
        # https://blog.gurock.com/announcing-testrail-6-7/
        # https://mirantis.jira.com/browse/PRODX-10103
        extra_headers = {'x-api-ident': 'beta'}

        res = cls._handler('GET', url, extra_headers, params=params)
        if type(res) is list:
            # Backward compatibility for unmodified APIs
            logger.info(f"Keep backward compatibility for '{name}' because "
                        f"pagination API is not enabled")
            return res
        elif type(res) is not dict:
            raise Exception(f"Response from pagination api {url} "
                            f"is not Dict: {res}")

        result = res[key_name]
        while res.get('_links', {}).get('next') is not None:
            url = res['_links']['next']
            res = cls._handler('GET', url, extra_headers, params=params)
            result.extend(res[key_name])
        return result

    def __getattr__(self, name):
        if name in self._data:
            return self._data[name]
        else:
            raise AttributeError

    def __setattr__(self, name, value):
        if '_data' in self.__dict__ and name not in self.__dict__:
            self.__dict__['_data'][name] = value
        else:
            self.__dict__[name] = value

    def __repr__(self):
        name = getattr(self, self._repr_field, '')
        name = repr(name)
        return '<{c.__name__}({s.id}) {name} at 0x{id:x}>'.format(
            s=self, c=self.__class__, id=id(self), name=name)

    @classmethod
    def get(cls, id):
        name = cls._api_name()
        url = cls._get_url.format(name=name, id=id)
        result = cls._handler('GET', url)
        if 'error' in result:
            raise Exception(result)
        return cls(**result)

    def update(self):
        url = self._update_url.format(name=self._api_name(), id=self.id)
        self._handler('POST', url, json=self.data)

    @property
    def data(self):
        return self._data


class Project(Item):
    @property
    def suites(self):
        return Collection(Suite, parent_id=self.id)

    @property
    def plans(self):
        return Collection(Plan, parent_id=self.id)

    @property
    def runs(self):
        return Collection(Run, parent_id=self.id)

    @property
    def milestones(self):
        return Collection(Milestone, parent_id=self.id)

    @property
    def configs(self):
        return Collection(Config, parent_id=self.id)


class Suite(Item):
    @property
    def cases(self):
        return CaseCollection(
            Case,
            _list_url='get_cases/{}&suite_id={}'.format(self.project_id,
                                                        self.id))

    @property
    def sections(self):
        url = 'get_sections/{}&suite_id={}'.format(self.project_id,
                                                   self.id)
        return self._pagination_handler(url, name='section')

    def get_custom_case_fields(self):
        url = 'get_case_fields'
        return self._pagination_handler(url, name='case_field')

    def get_section_by_name(self, section_name):
        return [section for section in self.sections
                if section['name'] == section_name][0]

    def get_section_id(self, section_name):
        return self.get_section_by_name(section_name)['id']

    def add_section(self, name):
        url = 'add_section/{}'.format(self.project_id)
        data = {
            'name': name,
            'suite_id': self.id,
        }
        result = self._handler('POST', url, json=data)
        return result


class CaseCollection(Collection):
    def _add(self, name, data, **kwargs):
        url = self._add_url.format(name=name)
        section_id = data.pop('section_id')
        data.pop('result', None)
        url = '{}/{}'.format(url, section_id)
        return self._handler('POST', url, json=data, **kwargs)


class Case(Item):
    _repr_field = 'title'

    def __init__(self, *args, **kwargs):
        super(Case, self).__init__(*args, **kwargs)
        self.result = None

    def add_result(self, **kwargs):
        self.result = Result(**kwargs)


class Plan(Item):
    def __init__(self,
                 name,
                 description=None,
                 milestone_id=None,
                 entries=None,
                 id=None,
                 **kwargs):
        add_kwargs = {
            'name': name,
            'description': description,
            'milestone_id': milestone_id,
            'entries': entries or [],
        }
        kwargs.update(add_kwargs)
        return super(self.__class__, self).__init__(id, **kwargs)

    @property
    def runs(self):
        return ItemSet([Run.get(id=run['id'])
                        for entry in self.entries for run in entry['runs']])

    def add_run(self, run, configuration=None):
        url = 'add_plan_entry/{}'.format(self.id)

        run_data = {
            k: v
            for k, v in run.data.items()
            if k in ('case_ids', 'config_ids', 'name', 'description')
        }
        prepared_runs = [run_data]
        configs = []
        if configuration:
            # Add test run for each inner configuration except already created
            for c in configuration['configs']:
                if c['id'] not in run.data['config_ids']:
                    prepared_runs.append(
                        {'case_ids': [],
                         'config_ids': [c['id']],
                         'name': run.name,
                         'description': run.description})
                    configs.append(c['id'])
        # The order matters
        configs.extend(run_data['config_ids'])
        entry = {
            "suite_id": run.suite_id,
            "name": run.name,
            "description": run.description,
            "config_ids": configs,
            "include_all": run.include_all,
            "case_ids": run.data['case_ids'],
            "runs": prepared_runs,
        }

        result = self._handler('POST', url, json=entry)
        new_run_data = [
            r for r in result['runs']
            if set(r['config_ids']) == set(run_data['config_ids'])][0]
        run.id = new_run_data.pop('id')
        run.data.update(new_run_data)

    def update_run(self, run):
        entry = [_entry
                 for _entry in self.entries for _run in _entry['runs']
                 if _run['id'] == run.id
                 ].pop()
        config_ids = []
        for _run in entry['runs']:
            config_ids.extend(_run['config_ids'])
        url = 'update_plan_entry/{0}/{1}'.format(self.id, entry['id'])
        update_data = {
            'name': run.data['name'],
            'description': run.data['description'],
            'assignedto_id': run.data['assignedto_id'],
            'include_all': run.data['include_all'],
            'case_ids': run.data['case_ids'],
        }
        if config_ids:
            update_data['config_ids'] = config_ids

        entry.update(self._handler('POST', url, json=update_data))


class Run(Item):
    def __init__(self,
                 suite_id=None,
                 milestone_id=None,
                 config_ids=(),
                 name="",
                 description="",
                 include_all=False,
                 case_ids=(),
                 assignedto_id=None,
                 id=None,
                 **kwargs):
        add_kwargs = locals()
        add_kwargs.pop('self')
        add_kwargs.pop('kwargs')
        add_kwargs.pop('id')
        add_kwargs.pop('__class__', None)  # always exists in Python 3

        kwargs.update(add_kwargs)
        return super(self.__class__, self).__init__(id, **kwargs)

    @property
    def tests(self):
        return Collection(Test, parent_id=self.id)

    @property
    def results(self):
        return ResultCollection(Result, parent_id=self.id)

    def add_results_for_cases(self, cases):
        if not self.include_all:
            # IDs can't be taken from self.case_ids set because it's always
            # empty now, see https://goo.gl/uunbEH
            cases_ids = [test.case_id for test in self.tests.list()]
            missing_cases_ids = [case.id for case in cases
                                 if case.id not in cases_ids]
            if missing_cases_ids:
                logger.debug('Adding {0} missing test cases '
                             'to the run'.format(len(missing_cases_ids)))
                self.case_ids = cases_ids + missing_cases_ids
                run_data = self.get(self.id)
                if hasattr(run_data, 'plan_id') and run_data.plan_id:
                    Plan.get(id=self.plan_id).update_run(run=self)
                else:
                    self.update()
        return self.results.add_for_cases(self.id, cases)


class Test(Item):
    pass


class ResultCollection(Collection):

    _list_url = 'get_results_for_run'

    def add_for_cases(self, run_id, cases):
        if len(cases) == 0:
            logger.warning('No cases with result for run {}'.format(run_id))
            return
        results = []
        for case in cases:
            if case.result is None:
                continue
            result = case.result.data
            result['case_id'] = case.id
            results.append(result)
        if results is not None:
            url = 'add_results_for_cases/{}'.format(run_id)
            result = self._handler('POST', url, json={'results': results})
            return [self._to_object(x) for x in result]
        else:
            return []


class Result(Item):
    def __init__(self,
                 status_id,
                 comment=None,
                 version=None,
                 elapsed=None,
                 defects=None,
                 assignedto_id=None,
                 id=None,
                 **kwargs):
        add_kwargs = {
            'status_id': status_id,
            'comment': comment,
            'version': version,
            'elapsed': elapsed,
            'defects': defects,
            'assignedto_id': assignedto_id,
        }

        kwargs.update(add_kwargs)
        return super(self.__class__, self).__init__(id, **kwargs)


class Milestone(Item):
    pass


class Config(Item):
    pass


class Client(object):
    def __init__(self, base_url, username, password, request_timeout=600):
        self.username = username
        self.password = password
        self.request_timeout = request_timeout
        self.base_url_root = base_url.rstrip('/') + '/index.php?'
        self.base_url = self.base_url_root + '/api/v2/'

        Item._handler = self._query

    def _query(self, method, url, extra_headers=None, **kwargs):
        if url.startswith('/api/v2/'):
            # for pagination APIs
            url = self.base_url_root + url
        else:
            url = self.base_url + url

        headers = {'Content-type': 'application/json'}
        if extra_headers:
            headers.update(extra_headers)

        logger.debug('Make {} request to {}'.format(method, url))

        def _time_sleep(resp, min_interval=300, max_interval=600):
            if resp is None:
                logger.info("Connection error to {}".format(url))
            else:
                logger.info("Request error to {0}\n"
                            "status_code: {1.status_code}\n"
                            "headers: {1.headers}\n"
                            "content: '{1.content}'".format(url, resp))
            sleep = random.randint(min_interval, max_interval)
            logger.info("Waiting for {} sec until next try".format(sleep))
            time.sleep(sleep)

        start_time = time.time()
        while True:
            try:
                response = requests.request(
                    method,
                    url,
                    allow_redirects=False,
                    auth=(self.username, self.password),
                    headers=headers,
                    **kwargs)
                if response.status_code < 300:
                    # Request processed successfuly
                    break

            except requests.ConnectionError:
                response = None

            if start_time + self.request_timeout > time.time():
                _time_sleep(response)
                continue

            # Out of tries, raise an error
            # ----------------------------

            # Raise the original requests.ConnectionError
            if response is None:
                raise
            # Redirect or error
            raise requests.HTTPError("Wrong response after trying {1} sec:\n"
                                     "status_code: {0.status_code}\n"
                                     "headers: {0.headers}\n"
                                     "content: '{0.content}'".format(response,
                                                              self.request_timeout),
                                     response=response)
        result = response.json()
        if 'error' in result:
            logger.warning(result)
        return result

    @property
    def projects(self):
        return Collection(Project)

    @property
    def statuses(self):
        statuses = self._query('GET', 'get_statuses')
        return {x['id']: x['name'] for x in statuses}
