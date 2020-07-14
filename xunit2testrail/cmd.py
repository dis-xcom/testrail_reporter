#!/usr/bin/env python

import argparse
import functools
import json
import logging
import os
import sys
import textwrap
import traceback
import warnings

import prettytable

from xunit2testrail import TemplateCaseMapper
from xunit2testrail import Reporter

warnings.simplefilter('always', DeprecationWarning)
logger = logging.getLogger(__name__)

if sys.version_info[0] == 3:
    str_cls = str
else:
    str_cls = eval('unicode')


def filename(string):
    if not os.path.exists(string):
        msg = "%r is not exists" % string
        raise argparse.ArgumentTypeError(msg)
    if not os.path.isfile(string):
        msg = "%r is not a file" % string
        raise argparse.ArgumentTypeError(msg)
    return string


def parse_args(args):
    defaults = {
        'TESTRAIL_URL': 'https://mirantis.testrail.com',
        'TESTRAIL_USER': 'user@example.com',
        'TESTRAIL_PASSWORD': 'password',
        'TESTRAIL_REQUEST_TIMEOUT': 3200,
        'TESTRAIL_PROJECT': 'Mirantis OpenStack',
        'TESTRAIL_MILESTONE': '9.0',
        'TESTRAIL_TEST_SUITE': '[{0.testrail_milestone}] MOSQA',
        'TESTRAIL_CASE_CUSTOM_FIELDS': {"custom_qa_team": "9", },
        'TESTRAIL_CASE_SECTION_NAME': 'All',
        'TESTRAIL_CONFIGURATION_NAME': None,
        'TESTRAIL_CASE_MAX_NAME_LENGHT': 0,
        'XUNIT_REPORT': 'report.xml',
        'XUNIT_NAME_TEMPLATE': '{id}',
        'TESTRAIL_NAME_TEMPLATE': '{custom_report_label}',
        'TESTRAIL_RUN_DESCRIPTION': (
            'Run **{test_run_name}** on #{test_plan_name}. \n'
            '[Test results]({test_results_link})'),
        'ISO_ID': None,
        'TESTRAIL_PLAN_NAME': None,
        'ENV_DESCRIPTION': '',
        'TEST_RESULTS_LINK': '',
        'PASTE_BASE_URL': None,
    }
    defaults = {k: os.environ.get(k, v) for k, v in defaults.items()}

    parser = argparse.ArgumentParser(description='xUnit to testrail reporter')
    parser.add_argument(
        'xunit_report',
        type=filename,
        default=defaults['XUNIT_REPORT'],
        help='xUnit report XML file')

    parser.add_argument(
        '--xunit-name-template',
        type=str_cls,
        default=defaults['XUNIT_NAME_TEMPLATE'],
        help='template for xUnit cases to make id string')
    parser.add_argument(
        '--testrail-name-template',
        type=str_cls,
        default=defaults['TESTRAIL_NAME_TEMPLATE'],
        help='template for TestRail cases to make id string')

    parser.add_argument(
        '--env-description',
        type=str_cls,
        default=defaults['ENV_DESCRIPTION'],
        help='env deploy type description (for TestRun name)')

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        '--iso-id',
        type=str_cls,
        default=defaults['ISO_ID'],
        help='id of build Fuel iso (DEPRECATED)')
    group.add_argument(
        '--testrail-plan-name',
        type=str_cls,
        default=defaults['TESTRAIL_PLAN_NAME'],
        help='name of test plan to be displayed in testrail')

    parser.add_argument(
        '--test-results-link',
        type=str_cls,
        default=defaults['TEST_RESULTS_LINK'],
        help='link to test job results')
    parser.add_argument(
        '--testrail-url',
        type=str_cls,
        default=defaults['TESTRAIL_URL'],
        help='base url of testrail')
    parser.add_argument(
        '--testrail-user',
        type=str_cls,
        default=defaults['TESTRAIL_USER'],
        help='testrail user')
    parser.add_argument(
        '--testrail-password',
        type=str_cls,
        default=defaults['TESTRAIL_PASSWORD'],
        help='testrail password')
    parser.add_argument(
        '--testrail-request-timeout',
        type=int,
        default=defaults['TESTRAIL_REQUEST_TIMEOUT'],
        help=('Timeout of waiting for a passed request to TestRail (HTTP status code < 300). '
              'Covers cases like HTTP-429 "API Rate Limit" or HTTP-409 "maintenance". '
              'During this period, the request will be repeated with random intervals (from 300 to 600 sec)'))
    parser.add_argument(
        '--testrail-project',
        type=str_cls,
        default=defaults['TESTRAIL_PROJECT'],
        help='testrail project name')
    parser.add_argument(
        '--testrail-milestone',
        type=str_cls,
        default=defaults['TESTRAIL_MILESTONE'],
        help='testrail project milestone')
    parser.add_argument(
        '--testrail-suite',
        type=str_cls,
        default=defaults['TESTRAIL_TEST_SUITE'],
        help='testrail project suite name')
    parser.add_argument(
        '--testrail-add-missing-cases',
        action='store_true',
        default=False,
        help='Update testrail suite with new cases from xunit report')
    parser.add_argument(
        '--testrail-case-custom-fields',
        type=json.loads,
        default=defaults['TESTRAIL_CASE_CUSTOM_FIELDS'],
        help=('Testrail custom fields for *new* cases in the suite in JSON format {"key": "id"}.'
              ' Requires --testrail-add-missing-cases. To see available fields, use with --dry-run .'))
    parser.add_argument(
        '--testrail-case-section-name',
        type=str_cls,
        default=defaults['TESTRAIL_CASE_SECTION_NAME'],
        help='Section name for *new* cases in the suite. Requires --testrail-add-missing-cases')
    parser.add_argument(
        '--testrail_configuration_name',
        type=str_cls,
        default=defaults['TESTRAIL_CONFIGURATION_NAME'],
        help='Name of the configuration to which test environment belongs to')
    parser.add_argument(
        '--testrail-case-max-name-lenght',
        type=int,
        default=defaults['TESTRAIL_CASE_MAX_NAME_LENGHT'],
        help=('Truncate test case name lenght from the XML report to the specified value, '
              'if TestRail has limited title lenght'))
    parser.add_argument(
        '--send-skipped',
        action='store_true',
        default=False,
        help='send skipped cases to testrail')
    parser.add_argument(
        '--send-duplicates',
        action='store_true',
        default=False,
        help='send duplicated cases to testrail')
    parser.add_argument(
        '--paste-url',
        type=str_cls,
        default=defaults['PASTE_BASE_URL'],
        help=('pastebin service JSON API URL to send test case logs and trace,'
              ' example: http://localhost:5000/'))
    parser.add_argument(
        '--testrail-run-update',
        dest='use_test_run_if_exists',
        action='store_true',
        default=False,
        help='don\'t create new test run if such already exists')
    parser.add_argument(
        '--testrail-run-description',
        type=str_cls,
        default=defaults['TESTRAIL_RUN_DESCRIPTION'],
        help='Use the specified description for *new* test runs')
    parser.add_argument(
        '--dry-run', '-n',
        action='store_true',
        default=False,
        help='Just print mapping table')
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        default=False,
        help='Verbose mode')

    return parser.parse_args(args)


def print_mapping_table(mapping, wrap=60):
    """Print mapping result table."""
    pt = prettytable.PrettyTable(field_names=['ID', 'Tilte', 'Xunit case'])
    pt.align = 'l'
    wrapper = functools.partial(
        textwrap.fill, width=wrap, break_long_words=False)
    for testrail_case, xunit_case in mapping.items():
        xunit_str = '{0.methodname}\n({0.classname})'.format(xunit_case)
        pt.add_row([
            testrail_case.id, wrapper(testrail_case.title), wrapper(xunit_str)
        ])
    print(pt)


def main(args=None):

    args = args or sys.argv[1:]

    args = parse_args(args)

    if not args.testrail_plan_name:
        args.testrail_plan_name = ('{0.testrail_milestone} iso '
                                   '#{0.iso_id}').format(args)

        msg = ("--iso-id parameter is DEPRECATED. "
               "It is recommended to use --testrail-plan-name parameter.")
        warnings.warn(msg, DeprecationWarning)

    logger_dict = dict(stream=sys.stderr)
    if args.verbose:
        logger_dict['level'] = logging.DEBUG

    logging.basicConfig(**logger_dict)

    case_mapper = TemplateCaseMapper(
        xunit_name_template=args.xunit_name_template,
        testrail_name_template=args.testrail_name_template,
        testrail_case_max_name_lenght=args.testrail_case_max_name_lenght)

    reporter = Reporter(
        xunit_report=args.xunit_report,
        env_description=args.env_description,
        test_results_link=args.test_results_link,
        case_mapper=case_mapper,
        paste_url=args.paste_url)
    suite = args.testrail_suite.format(args)
    reporter.config_testrail(
        base_url=args.testrail_url,
        username=args.testrail_user,
        password=args.testrail_password,
        milestone=args.testrail_milestone,
        project=args.testrail_project,
        plan_name=args.testrail_plan_name,
        tests_suite=suite,
        send_skipped=args.send_skipped,
        send_duplicates=args.send_duplicates,
        use_test_run_if_exists=args.use_test_run_if_exists,
        testrail_add_missing_cases=args.testrail_add_missing_cases,
        testrail_case_custom_fields=args.testrail_case_custom_fields,
        testrail_case_section_name=args.testrail_case_section_name,
        testrail_configuration_name=args.testrail_configuration_name,
        dry_run=args.dry_run,
        request_timeout=args.testrail_request_timeout)

    xunit_suite, _ = reporter.get_xunit_test_suite()
    mapping = reporter.map_cases(xunit_suite)
    if not args.dry_run:
        cases = reporter.fill_case_results(mapping)
        if len(cases) == 0:
            logger.warning('No cases matched, program will terminated')
            return
        plan = reporter.get_or_create_plan()
        run_description = args.testrail_run_description
        test_run = reporter.get_or_create_test_run(plan, cases,
                                                   run_description)
        test_run.add_results_for_cases(cases)
        reporter.print_run_url(test_run)
    else:
        print_mapping_table(mapping)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)
