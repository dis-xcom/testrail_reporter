import requests_mock
import pytest
import json
import re
from functools import partial
import six

from xunit2testrail import Reporter
from xunit2testrail.testrail.client import Client

if six.PY2:
    import mock
else:
    from unittest import mock


@pytest.yield_fixture
def api_mock():
    with requests_mock.Mocker() as m:
        yield m


@pytest.fixture
def testrail_client(mocker):
    fake_statuses = mock.PropertyMock(return_value={1: 'passed', 2: 'skipped'})
    mocker.patch(
        'xunit2testrail.reporter.TrClient.statuses',
        new_callable=fake_statuses)
    return


@pytest.fixture
def reporter(testrail_client):
    reporter = Reporter(
        xunit_report='tests/xunit_files/report.xml',
        env_description='vlan_ceph',
        test_results_link="http://test_job/",
        case_mapper=None,
        paste_url='http://example.com/')
    reporter.config_testrail(
        base_url="https://testrail",
        username="user",
        password="password",
        milestone="0.1",
        project="Test Project",
        tests_suite="Test Suite",
        plan_name="Plan name")
    return reporter


def _testrail_callback(data_kind):

    project_response = {1: {'id': 1}}
    suite_response = {2: {'id': 2, 'project_id': 1}}
    case_response = {
        3: {
            'id': 3,
            'suite_id': 2,
            'title': 'case title'
        },
        31: {
            'id': 31,
            'suite_id': 2,
            'title': 'case title31'
        },
    }
    run_response = {
        4: {
            'id': 4,
            'project_id': 1,
            'suite_id': 2,
            'milestone_id': 8,
            'config_ids': [9],
            'plan_id': None,
        },
        13: {
            'id': 13,
            'project_id': 1,
            'suite_id': 2,
            'milestone_id': 8,
            'config_ids': [9],
            'plan_id': 8,
            'name': 'some test run',
            'description': None,
            'assignedto_id': None,
            'case_ids': []
        },
    }
    result_response = {5: {'id': 5, 'status_id': 6}}
    status_response = {6: {'id': 6, 'name': 'passed'}}
    plan_response = {7: {'id': 7, 'project_id': 1, 'name': 'old_test_plan'},
                     8: {'id': 8, 'project_id': 1, 'name': 'new_test_plan',
                         'entries': [{'runs': [{'id': 13,
                                                'name': 'some test run',
                                                'config_ids': [9]}],
                                      'id': 12}]}}
    milestone_response = {8: {'id': 8, 'project_id': 1}}
    config_response = {9: {'id': 9, 'project_id': 1}}
    test_response = {10: {'id': 10, 'run_id': 4, 'case_id': 5}}
    case_fields_response = {11:
        {'system_name': 'custom_qa_team',
         'include_all': True,
         'name': 'qa_team',
         'type_id': 6,
         'id': 35,
         'template_ids': [],
         'display_order': 5,
         'is_active': True,
         'label': 'QA team',
         'description': None,
         'configs': [{
             'options': {
                 'default_value': '',
                 'context': {'is_global': True,
                             'project_ids': []},
                 'items': ('1, Framework-CI\n'
                           '2, Fuel\n'
                           '3, Maintenance\n'
                           '4, MOS\n'
                           '5, Performance\n'
                           '6, PCE\n'
                           '7, Telco\n'
                           '8, CI-bot\n'
                           '9, MCP\n'
                           '10, LDAP plugin QA\n'
                           '11, StackLight plugin QA\n'
                           '12, Murano plugin QA\n'
                           '13, CCE'),
                 'is_required': True},
             'id': 'd5216a64-8be8-4284-ac38-07aad92504db'}]
        }}

    def callback(request, context, _data):
        context.status_code = 200
        _id = request.query.split('get_{}/'.format(data_kind))[-1]
        if _id.isdigit():
            data = _data[int(_id)]
        else:
            data = list(_data.values())
        return json.dumps(data)

    data = locals().get(data_kind + '_response')

    return partial(callback, _data=data)


@pytest.fixture
def client(api_mock):
    client = Client(
        base_url='http://testrail/', username='user', password='password')

    base = re.escape(client.base_url)

    api_mock.register_uri(
        'GET',
        re.compile(base + r'get_project(s|/).*'),
        text=_testrail_callback('project'),
        complete_qs=True)
    api_mock.register_uri(
        'GET',
        re.compile(base + r'get_suite(s|/).*'),
        text=_testrail_callback('suite'),
        complete_qs=True)
    api_mock.register_uri(
        'GET',
        re.compile(base + r'get_case_field(s|/).*'),
        text=_testrail_callback('case_fields'),
        complete_qs=True)
    api_mock.register_uri(
        'GET',
        re.compile(base + r'get_case(s|/).*'),
        text=_testrail_callback('case'),
        complete_qs=True)
    api_mock.register_uri(
        'GET',
        re.compile(base + r'get_plan(s|/).*'),
        text=_testrail_callback('plan'),
        complete_qs=True)
    api_mock.register_uri(
        'GET',
        re.compile(base + r'get_run(s|/).*'),
        text=_testrail_callback('run'),
        complete_qs=True)
    api_mock.register_uri(
        'GET',
        re.compile(base + r'get_result(s|/).*'),
        text=_testrail_callback('result'),
        complete_qs=True)
    api_mock.register_uri(
        'GET',
        re.compile(base + r'get_status(es|/).*'),
        text=_testrail_callback('status'),
        complete_qs=True)
    api_mock.register_uri(
        'GET',
        re.compile(base + r'get_milestone(s|/).*'),
        text=_testrail_callback('milestone'),
        complete_qs=True)
    api_mock.register_uri(
        'GET',
        re.compile(base + r'get_config(s|/).*'),
        text=_testrail_callback('config'),
        complete_qs=True)
    api_mock.register_uri(
        'GET',
        re.compile(base + r'get_test(s|/).*'),
        text=_testrail_callback('test'),
        complete_qs=True)
    return client


@pytest.fixture
def project(client):
    projects = client.projects()
    return projects[0]


@pytest.fixture
def suite(project):
    suites = project.suites()
    return suites[0]


@pytest.fixture
def case(suite):
    cases = suite.cases()
    return cases[0]


@pytest.fixture
def run(project):
    runs = project.runs()
    return runs[0]


@pytest.fixture
def test(run):
    tests = run.tests()
    return tests[0]


@pytest.fixture
def milestone(project):
    milestones = project.milestones()
    return milestones[0]


@pytest.fixture
def plan(project):
    plans = project.plans()
    return next(p for p in plans if p.id == 8)


@pytest.fixture
def config(project):
    configs = project.configs()
    return configs[0]
