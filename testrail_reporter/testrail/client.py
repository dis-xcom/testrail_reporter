import logging
import re

import requests

logger = logging.getLogger(__name__)

requests_logger = logging.getLogger('requests.packages.urllib3')
requests_logger.setLevel(logging.WARNING)


class ItemSet(list):
    def __init__(self, *args, **kwargs):
        self._item_class = None
        return super(self.__class__, self).__init__(*args, **kwargs)

    def find_all(self, **kwargs):
        filtered = ItemSet(x for x in self if
                           all(getattr(x, k) == v for k, v in kwargs.items()))
        filtered._item_class = self._item_class
        return filtered

    def find(self, **kwargs):
        items = self.find_all(**kwargs)
        if items:
            return items[0]


class Collection(object):

    list_url = 'get_{name}s'
    add_url = 'add_{name}'

    def __init__(self, item_class=None, parent_id=None, **kwargs):
        self._item_class = item_class
        self._handler = self._item_class._handler
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
            return items

        else:
            return self.get(id)

    def __repr__(self):
        return '<Collection of {}>'.format(self._item_class.__name__)

    def _to_object(self, data):
        return self._item_class(**data)

    def _list(self, name, params=None):
        params = params or {}
        url = self.list_url.format(name=name)
        if self.parent_id is not None:
            url += '/{}'.format(self.parent_id)
        return self._handler('GET', url, params=params)

    def _add(self, name, data, **kwargs):
        url = self.add_url.format(name=name)
        if self.parent_id is not None:
            url += '/{}'.format(self.parent_id)
        return self._handler('POST', url, json=data, **kwargs)

    def find_all(self, **kwargs):
        return self().find_all(**kwargs)

    def find(self, **kwargs):
        return self().find(**kwargs)

    def get(self, id):
        return self._item_class.get(id)

    def add(self, *args, **kwargs):
        if len(args) > 1:
            raise TypeError(
                'add() takes zero or one argument ({} given)'.format(
                    len(args)))
        elif len(args) == 1:
            item = args[0]
            if not isinstance(item, self._item_class):
                raise TypeError('arg must be an instance of {}'.format(
                    self._item_class))
        else:
            item = self._to_object(kwargs)
        result = self._add(item._api_name(), item.data)
        return self._to_object(result)


class Item(object):
    get_url = 'get_{name}/{id}'
    update_url = 'update_{name}/{id}'
    _handler = None
    repr_field = 'name'

    def __init__(self, id=None, **kwargs):
        self.id = id
        self._data = kwargs

    @classmethod
    def _api_name(cls):
        name = re.sub(r'([A-Z])', r'_\1', cls.__name__).strip('_')
        return name.lower()

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
        name = getattr(self, self.repr_field, '')
        name = repr(name)
        return '<{c.__name__}({s.id}) {name} at 0x{id:x}>'.format(
            s=self, c=self.__class__, id=id(self), name=name)

    @classmethod
    def get(cls, id):
        name = cls._api_name()
        url = cls.get_url.format(name=name, id=id)
        result = cls._handler('GET', url)
        if 'error' in result:
            raise Exception(result)
        return cls(**result)

    def update(self):
        url = self.update_url.format(name=self._api_name(), id=self.id)
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
        return Collection(Case, list_url='get_cases/{}&suite_id={}'.format(
            self.project_id, self.id))


class Case(Item):
    repr_field = 'title'

    def __init__(self, *args, **kwargs):
        super(Case, self).__init__(*args, **kwargs)
        self.result = None

    def add_result(self, **kwargs):
        self.result = Result(**kwargs)


class Plan(Item):
    def __init__(self, name, description=None, milestone_id=None,
                 entries=None, id=None, **kwargs):
        add_kwargs = locals()
        add_kwargs.pop('self')
        add_kwargs.pop('kwargs')
        add_kwargs.pop('id')
        add_kwargs['entries'] = entries or []

        kwargs.update(add_kwargs)
        return super(self.__class__, self).__init__(id, **kwargs)

    @property
    def entries(self):
        return PlanEntryCollection(PlanEntry,
                                   list_url='get_plan/{}'.format(self.id),
                                   parent_id=self.id)

    def add_run(self, run):
        url = 'add_plan_entry/{}'.format(self.id)
        run_data = {k: v for k, v in run.data.items()
                    if k in ('case_ids', 'config_ids', 'name', 'description')}
        request = {
            "suite_id": run.suite_id,
            "name": run.name,
            "description": run.description,
            "config_ids": run.config_ids,
            "include_all": run.include_all,
            "case_ids": run.data['case_ids'],
            "runs": [run_data],
        }
        result = self._handler('POST', url, json=request)
        run.id = result['runs'][0]['id']


class PlanEntryCollection(Collection):
    def _list(self, name, params=None):
        plan = Plan.get(self.parent_id)
        entries = plan.data['entries']
        for entry in entries:
            entry['plan_id'] = self.parent_id
        return entries

    def get(self, id):
        return self().find(id=id)


class PlanEntry(Item):
    def __init__(self, suite_id, name="", description="", include_all=False,
                 config_ids=(), case_ids=(), runs=(), assignedto_id=None,
                 id=None, plan_id=None, **kwargs):
        add_kwargs = locals()
        add_kwargs.pop('self')
        add_kwargs.pop('kwargs')
        add_kwargs.pop('id')
        self.plan_id = add_kwargs.pop('plan_id')

        kwargs.update(add_kwargs)
        return super(self.__class__, self).__init__(id, **kwargs)

    @classmethod
    def get(cls, id):
        raise Exception("Use Plan.entries.get() instead")

    def update(self):
        url = 'update_plan_entry/{}/{}'.format(self.plan_id, self.id)
        data = {k: v for (k, v) in self.data.items()
                if k in ("name", "description", "assignedto_id", "include_all",
                         "case_ids")}
        self._handler('POST', url, json=data)


class Run(Item):
    def __init__(self, suite_id, milestone_id, config_ids=(), name="",
                 description="", include_all=False, case_ids=(),
                 assignedto_id=None, id=None, **kwargs):
        add_kwargs = locals()
        add_kwargs.pop('self')
        add_kwargs.pop('kwargs')
        add_kwargs.pop('id')

        kwargs.update(add_kwargs)
        return super(self.__class__, self).__init__(id, **kwargs)

    @property
    def tests(self):
        return Collection(Test, parent_id=self.id)

    @property
    def results(self):
        return ResultCollection(Result, parent_id=self.id,
            list_url='get_results_for_run')

    def add_results_for_cases(self, cases):
        return self.results.add_for_cases(self.id, cases)


class Test(Item):
    pass


class ResultCollection(Collection):
    def add_for_cases(self, run_id, cases):
        if len(cases) == 0:
            logger.warning('No cases with result for run {}'.format(run_id))
            return
        results = []
        for case in cases:
            result = case.result.data
            result['case_id'] = case.id
            results.append(result)
        url = 'add_results_for_cases/{}'.format(run_id)
        result = self._handler('POST', url, json={'results': results})
        return [self._to_object(x) for x in result]


class Result(Item):
    def __init__(self, status_id, comment=None, version=None, elapsed=None,
                 defects=None, assignedto_id=None, id=None, **kwargs):
        add_kwargs = locals()
        add_kwargs.pop('self')
        add_kwargs.pop('kwargs')
        add_kwargs.pop('id')

        kwargs.update(add_kwargs)
        return super(self.__class__, self).__init__(id, **kwargs)


class Milestone(Item):
    pass


class Config(Item):
    pass


class Client(object):

    def __init__(self, base_url, username, password):
        self.username = username
        self.password = password
        self._base_url = base_url

        Item._handler = self._query

    @property
    def base_url(self):
        url = self._base_url.rstrip('/')
        return '{}/index.php?/api/v2/'.format(url)

    def _query(self, method, url, **kwargs):
        url = self.base_url + url
        kwargs['auth'] = (self.username, self.password)
        kwargs['headers'] = {'Content-type': 'application/json'}
        logger.debug('Make {} request to {}'.format(method, url))
        response = requests.request(
            method, url, allow_redirects=False, **kwargs)
        if response.status_code >= 300:
            raise Exception(
                "Wrong response:\n"
                "status_code: {0.status_code}\n"
                "headers: {0.headers}\n"
                "content: '{0.content}'".format(response))
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
