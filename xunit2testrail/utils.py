import abc
import re
from uuid import UUID
from collections import defaultdict
import logging

import prettytable
import six

logger = logging.getLogger(__name__)


def find_id(methodname):
    """Returns test id from name
    For example if test name is "test_ban_l3_agent[once][(12345)]"
    it returns 12345
    """
    result = re.search(r'\((?P<id>\d{4,})\)', methodname)
    if result is not None:
        return result.group('id')


def find_uuid(methodname):
    """Returns uuid from test methodname (if exists)
    For example if test name is
        "test_quotas[id-2390f766-836d-40ef-9aeb-e810d78207fb,network]"
    it returns 2390f766-836d-40ef-9aeb-e810d78207fb

    Matching variants:
        * test_quotas[id-2390f766-836d-40ef-9aeb-e810d78207fb]
        * test_quotas[id-2390f766-836d-40ef-9aeb-e810d78207fb,network]
    """
    result = re.search(r'\[(?:.*,)?id-(?P<id>.+?)(?:,.+)?\]', methodname)
    if result is not None:
        try:
            uuid = UUID(hex=result.group('id'))
            return str(uuid)
        except ValueError:
            pass


class NoneValueException(Exception):
    """None value exception class."""


class NotNoneValue(object):
    """Value wrapper with not None checker."""

    def __init__(self, value):
        self._value = value

    def __str__(self):
        if self._value is None:
            raise NoneValueException(self._value)
        return str(self._value)

    def __repr__(self):
        return '{!r}'.format(self._value)

    @property
    def value(self):
        return self._value


@six.add_metaclass(abc.ABCMeta)
class CaseMapper(object):
    def describe_xunit_case(self, case):
        xunit_dict = {
            'classname': case.classname,
            'methodname': case.methodname,
            'id': case.report_id or find_id(case.methodname),
            'uuid': find_uuid(case.methodname)
        }

        return {k: NotNoneValue(v) for k, v in xunit_dict.items()}

    def describe_testrail_case(self, case):
        return {
            k: v
            for k, v in case.data.items() if isinstance(v, six.string_types)
        }

    def print_pair_data(self, testrail_case, xunit_case):
        testrail_fields = self.describe_testrail_case(testrail_case)
        print('Available TestRail fields (case {.id}):'.format(testrail_case))
        pt = prettytable.PrettyTable(field_names=['Name', 'Value'])
        pt.align = 'l'
        for k, v in testrail_fields.items():
            pt.add_row([k, v])
        print(pt)

        xunit_fields = self.describe_xunit_case(xunit_case)
        print('Available xUnit fields:')
        pt = prettytable.PrettyTable(field_names=['Name', 'Value'])
        pt.align = 'l'
        for k, v in xunit_fields.items():
            pt.add_row([k, v.value])
        print(pt)

    def _check_collisions(self, mapping, allow_duplicates=False):
        """Check cases collisions."""
        def get_duplicates(array, pos):
            grouped = defaultdict(list)
            for el in array:
                el = list(el)
                index = el.pop(pos)
                grouped[index].append(el[0])
            return [(k, v) for k, v in grouped.items() if len(v) > 1]

        if not allow_duplicates:
            duplicated_xunit_cases = get_duplicates(mapping, 0)
            if duplicated_xunit_cases:
                logger.error(
                    'Found xunit cases matches to single testrail case:')
                for tr_case, xu_cases in duplicated_xunit_cases:
                    for xu_case in xu_cases:
                        logger.error(
                            'TestRail "{0.title}" - xUnit "{1.classname}.'
                            '{1.methodname}"'.format(tr_case, xu_case))
                raise Exception("Can't map some xunit cases")
            duplicated_testrail_cases = get_duplicates(mapping, 1)
            if duplicated_testrail_cases:
                logger.error(
                    'Found testrail cases matches to single xunit case:')
                for xu_case, tr_cases in duplicated_testrail_cases:
                    for tr_case in tr_cases:
                        logger.error('xUnit "{1.classname}.{1.methodname} - '
                                     'TestRail "{0.title}"'.format(tr_case,
                                                                   xu_case))
                raise Exception("Can't map some testrail cases")

    @abc.abstractmethod
    def get_suitable_cases(self, xunit_case, cases):
        """Return all suitable testrail cases for xunit case."""

    def map(self, xunit_suite, testrail_cases, testrail_suite,
            testrail_milestone_id, allow_duplicates=False,
            testrail_add_missing_cases=False, testrail_case_custom_fields=None,
            testrail_case_section_name=None, dry_run=False):
        mapping = []
        cases_collection = testrail_suite.cases
        custom_case_fields = testrail_suite.get_custom_case_fields()
        custom_case_items = ["{}:\n{}".format(
                x['system_name'],
                x['configs'][0]['options']['items'] if 'items' in x['configs'][0]['options'] else '')
            for x in custom_case_fields]
        logger.info("Available custom fields for cases: \n{}"
                    .format("\n".join(custom_case_items)))

        for xunit_case in xunit_suite:
            suitable_cases = self.get_suitable_cases(xunit_case,
                                                     testrail_cases)
            if len(suitable_cases) == 0:
                logger.warning(
                    "xUnit case `{0}` doesn't match "
                    "any TestRail Case".format(xunit_case))

                if testrail_add_missing_cases:
                    xunit_id = self.get_xunit_id(xunit_case)

                    steps = [{"": "passed"}, ]
                    case = {
                        "title": xunit_id,
                        "milestone_id": testrail_milestone_id,
                        "custom_test_case_description": xunit_id,
                        "custom_test_case_steps": steps,
                    }
                    case.update(testrail_case_custom_fields or {})

                    testrail_section_name = testrail_case_section_name or "All"

                    if not dry_run:
                        logger.info("Add missing case `{case}` to the TestRail suite "
                                    "`{suite}`".format(case=xunit_case,
                                                       suite=testrail_suite.name))
                        section_names = (sect['name'] for sect in testrail_suite.sections)
                        if testrail_section_name not in section_names:
                            testrail_suite.add_section(testrail_section_name)

                        section_id = testrail_suite.get_section_id(testrail_section_name)
                        added_case = cases_collection.add(section_id=section_id, **case)

                        suitable_cases = [added_case]
                    else:
                        logger.info("[dry run] Add missing case `{case}` to the TestRail suite "
                                    "`{suite}`".format(case=xunit_case,
                                                       suite=testrail_suite.name))
            for testrail_case in suitable_cases:
                mapping.append((testrail_case, xunit_case))

        if len(mapping) == 0 and all([xunit_suite.countTestCases(),
                                      len(testrail_cases)]):
            self.print_pair_data(testrail_cases[-1], xunit_case)
        self._check_collisions(mapping, allow_duplicates=allow_duplicates)
        return dict(mapping)


class TemplateCaseMapper(CaseMapper):
    """Template string based mapper."""

    def __init__(self, xunit_name_template, testrail_name_template,
                 testrail_case_max_name_lenght=0, **kwargs):
        super(TemplateCaseMapper, self).__init__(**kwargs)
        self.xunit_name_template = xunit_name_template
        self.testrail_name_template = testrail_name_template
        self.testrail_case_max_name_lenght = testrail_case_max_name_lenght

    def get_xunit_id(self, xunit_case):
        """Extract xUnit case fields and compose a case title for TestRail"""
        xunit_dict = self.describe_xunit_case(xunit_case)
        xunit_id = self.xunit_name_template.format(**xunit_dict)
        if self.testrail_case_max_name_lenght:
            return str(xunit_id)[:self.testrail_case_max_name_lenght]
        else:
            return xunit_id

    def get_suitable_cases(self, xunit_case, cases):
        try:
            xunit_id = self.get_xunit_id(xunit_case)
        except NoneValueException as e:
            logger.warning(
                "{e!r}: Can't extract {template} from `{case}`".format(
                    e=e, template=self.xunit_name_template, case=xunit_case))
            return []

        # Search symbols groups, which is absent in xunit_id
        split_symbols_base = [r'a-zA-Z', r'\(\)', r'\[\]', r',', ]
        split_symbols = ''
        for group in split_symbols_base:
            if re.search(r'[{}]'.format(group), xunit_id) is None:
                split_symbols += group

        split_expr = re.compile(r'[{}]'.format(split_symbols))\
            if split_symbols else None
        match_cases = []
        for case in cases:
            case_data = self.describe_testrail_case(case)
            testrail_id = self.testrail_name_template.format(**case_data)

            if split_expr is None:
                if xunit_id == testrail_id:
                    match_cases.append(case)
            else:
                groups = [x for x in split_expr.split(testrail_id) if x]
                groups.reverse()
                for group in groups:
                    if group == xunit_id:
                        match_cases.append(case)
        return match_cases


def truncate_head(banner, text, max_len):
    max_text_len = min(max_len - len(banner), len(text))
    start = '...\n'
    if max_text_len < len(text):
        max_text_len -= len(start)
        text = start + text[-max_text_len:]
    return banner + text
