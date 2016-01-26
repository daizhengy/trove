# Copyright 2015 Tesora Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import getpass
import os

from mock import DEFAULT
from mock import MagicMock
from mock import patch
from proboscis.asserts import assert_equal
from proboscis.asserts import assert_true

from trove.common.context import TroveContext
from trove.common import exception
from trove.guestagent.common import operating_system
from trove.guestagent.datastore import manager
from trove.guestagent import guest_log
from trove.tests.unittests import trove_testtools


class MockManager(manager.Manager):
    def __init__(self):
        super(MockManager, self).__init__('mysql')
        self._app = MagicMock()
        self._status = MagicMock()
        self._configuration_manager = MagicMock()

    @property
    def app(self):
        return self._app

    @property
    def status(self):
        return self._status

    @property
    def configuration_manager(self):
        return self._configuration_manager


class ManagerTest(trove_testtools.TestCase):
    def setUp(self):
        super(ManagerTest, self).setUp()

        self.chmod_patch = patch.object(operating_system, 'chmod')
        self.chmod_mock = self.chmod_patch.start()
        self.addCleanup(self.chmod_patch.stop)

        self.manager = MockManager()
        self.context = TroveContext()

        self.log_name_sys = 'guest'
        self.log_name_user = 'general'
        self.prefix = 'log_prefix'
        self.container = 'log_container'
        self.size = 1024
        self.published = 128
        self.guest_log_user = guest_log.GuestLog(
            self.context, self.log_name_user, guest_log.LogType.USER, None,
            '/tmp/gen.log', True)
        self.guest_log_sys = guest_log.GuestLog(
            self.context, self.log_name_sys, guest_log.LogType.SYS, None,
            '/tmp/guest.log', True)
        for gl in [self.guest_log_user, self.guest_log_sys]:
            gl._container_name = self.container
            gl._refresh_details = MagicMock()
            gl._log_rotated = MagicMock(return_value=False)
            gl._publish_to_container = MagicMock()
            gl._delete_log_components = MagicMock()
            gl._object_prefix = MagicMock(return_value=self.prefix)
            gl._size = self.size
            gl._published_size = self.published
        self.manager._guest_log_cache = {
            self.log_name_user: self.guest_log_user,
            self.log_name_sys: self.guest_log_sys}
        self.expected_details_user = {
            'status': 'Disabled',
            'prefix': self.prefix,
            'container': self.container,
            'name': self.log_name_user,
            'published': self.published,
            'metafile': self.prefix + '_metafile',
            'type': 'USER',
            'pending': self.size - self.published}
        self.expected_details_sys = dict(self.expected_details_user)
        self.expected_details_sys['type'] = 'SYS'
        self.expected_details_sys['status'] = 'Enabled'
        self.expected_details_sys['name'] = self.log_name_sys

    def tearDown(self):
        super(ManagerTest, self).tearDown()

    def test_update_status(self):
        self.manager.update_status(self.context)
        self.manager.status.update.assert_any_call()

    def test_guest_log_list(self):
        log_list = self.manager.guest_log_list(self.context)
        expected = [self.expected_details_sys, self.expected_details_user]
        assert_equal(self._flatten_list_of_dicts(expected),
                     self._flatten_list_of_dicts(log_list),
                     "Wrong list: %s (Expected: %s)" % (
                         self._flatten_list_of_dicts(log_list),
                         self._flatten_list_of_dicts(expected)))

    def _flatten_list_of_dicts(self, lod):
        value = sorted("".join("%s%s" % (k, d[k]) for k in sorted(d.keys()))
                       for d in lod)
        return "".join(sorted(value))

    def test_guest_log_action_enable_disable(self):
        self.assertRaisesRegexp(exception.BadRequest,
                                "Cannot enable and disable",
                                self.manager.guest_log_action,
                                self.context,
                                self.log_name_sys,
                                True, True, False, False)

    def test_guest_log_action_enable_sys(self):
        self.assertRaisesRegexp(exception.BadRequest,
                                "Cannot enable a SYSTEM log",
                                self.manager.guest_log_action,
                                self.context,
                                self.log_name_sys,
                                True, False, False, False)

    def test_guest_log_action_disable_sys(self):
        self.assertRaisesRegexp(exception.BadRequest,
                                "Cannot disable a SYSTEM log",
                                self.manager.guest_log_action,
                                self.context,
                                self.log_name_sys,
                                False, True, False, False)

    def test_guest_log_action_publish_sys(self):
        with patch.object(os.path, 'isfile', return_value=True):
            log_details = self.manager.guest_log_action(self.context,
                                                        self.log_name_sys,
                                                        False, False,
                                                        True, False)
            assert_equal(log_details, self.expected_details_sys,
                         "Wrong details: %s (expected %s)" %
                         (log_details, self.expected_details_sys))
            assert_equal(
                1, self.guest_log_sys._publish_to_container.call_count)

    def test_guest_log_action_discard_sys(self):
        log_details = self.manager.guest_log_action(self.context,
                                                    self.log_name_sys,
                                                    False, False,
                                                    False, True)
        assert_equal(log_details, self.expected_details_sys,
                     "Wrong details: %s (expected %s)" %
                     (log_details, self.expected_details_sys))
        assert_equal(
            1, self.guest_log_sys._delete_log_components.call_count)

    def test_guest_log_action_enable_user(self):
        with patch.object(manager.Manager, 'guest_log_enable',
                          return_value=False) as mock_enable:
            log_details = self.manager.guest_log_action(self.context,
                                                        self.log_name_user,
                                                        True, False,
                                                        False, False)
            assert_equal(log_details, self.expected_details_user,
                         "Wrong details: %s (expected %s)" %
                         (log_details, self.expected_details_user))
            assert_equal(1, mock_enable.call_count)

    def test_guest_log_action_disable_user(self):
        with patch.object(manager.Manager, 'guest_log_enable',
                          return_value=False) as mock_enable:
            self.guest_log_user._enabled = True
            log_details = self.manager.guest_log_action(self.context,
                                                        self.log_name_user,
                                                        False, True,
                                                        False, False)
            assert_equal(log_details, self.expected_details_user,
                         "Wrong details: %s (expected %s)" %
                         (log_details, self.expected_details_user))
            assert_equal(1, mock_enable.call_count)

    def test_guest_log_action_publish_user(self):
        with patch.object(manager.Manager, 'guest_log_enable',
                          return_value=False) as mock_enable:
            with patch.object(os.path, 'isfile', return_value=True):
                log_details = self.manager.guest_log_action(self.context,
                                                            self.log_name_user,
                                                            False, False,
                                                            True, False)
                assert_equal(log_details, self.expected_details_user,
                             "Wrong details: %s (expected %s)" %
                             (log_details, self.expected_details_user))
                assert_equal(1, mock_enable.call_count)

    def test_guest_log_action_discard_user(self):
        log_details = self.manager.guest_log_action(self.context,
                                                    self.log_name_user,
                                                    False, False,
                                                    False, True)
        assert_equal(log_details, self.expected_details_user,
                     "Wrong details: %s (expected %s)" %
                     (log_details, self.expected_details_user))
        assert_equal(1, self.guest_log_user._delete_log_components.call_count)

    def test_set_guest_log_status_disabled(self):
        data = [
            {'orig': guest_log.LogStatus.Enabled,
             'new': guest_log.LogStatus.Disabled,
             'expect': guest_log.LogStatus.Disabled},
            {'orig': guest_log.LogStatus.Restart_Required,
             'new': guest_log.LogStatus.Enabled,
             'expect': guest_log.LogStatus.Restart_Required},
            {'orig': guest_log.LogStatus.Restart_Required,
             'new': guest_log.LogStatus.Restart_Completed,
             'expect': guest_log.LogStatus.Restart_Completed},
            {'orig': guest_log.LogStatus.Published,
             'new': guest_log.LogStatus.Partial,
             'expect': guest_log.LogStatus.Partial},
        ]
        for datum in data:
            self.assert_guest_log_status(datum['orig'],
                                         datum['new'],
                                         datum['expect'])

    def assert_guest_log_status(self, original_status, new_status,
                                expected_final_status):
        gl_cache = self.manager.guest_log_cache
        gl_cache[self.log_name_sys]._status = original_status
        self.manager.set_guest_log_status(new_status, self.log_name_sys)
        assert_equal(gl_cache[self.log_name_sys].status, expected_final_status,
                     "Unexpected status for '%s': %s' (Expected %s)" %
                     (self.log_name_sys, gl_cache[self.log_name_sys].status,
                      expected_final_status))

    def test_build_log_file_name(self):
        current_owner = getpass.getuser()
        with patch.multiple(operating_system,
                            exists=MagicMock(return_value=False),
                            write_file=DEFAULT,
                            create_directory=DEFAULT,
                            chown=DEFAULT,
                            chmod=DEFAULT) as os_mocks:
            log_file = self.manager.build_log_file_name(self.log_name_sys,
                                                        current_owner)
            expected_filename = '%s/%s/%s-%s.log' % (
                self.manager.GUEST_LOG_BASE_DIR,
                self.manager.GUEST_LOG_DATASTORE_DIRNAME,
                self.manager.manager, self.log_name_sys)
            expected_call_counts = {'exists': 1,
                                    'write_file': 1,
                                    'create_directory': 2,
                                    'chown': 1,
                                    'chmod': 1}
            self.assert_build_log_file_name(expected_filename, log_file,
                                            os_mocks, expected_call_counts)

    def assert_build_log_file_name(self, expected_filename, filename,
                                   mocks, call_counts):
        assert_equal(expected_filename, filename,
                     "Unexpected filename: %s (expected %s)" %
                     (filename, expected_filename))
        for key in mocks.keys():
            assert_true(
                mocks[key].call_count == call_counts[key],
                "%s called %d time(s)" % (key, mocks[key].call_count))

    def test_build_log_file_name_with_dir(self):
        current_owner = getpass.getuser()
        log_dir = '/tmp'
        with patch.multiple(operating_system,
                            exists=MagicMock(return_value=False),
                            write_file=DEFAULT,
                            create_directory=DEFAULT,
                            chown=DEFAULT,
                            chmod=DEFAULT) as os_mocks:
            log_file = self.manager.build_log_file_name(self.log_name_sys,
                                                        current_owner,
                                                        datastore_dir=log_dir)
            expected_filename = '%s/%s-%s.log' % (
                log_dir,
                self.manager.manager, self.log_name_sys)
            expected_call_counts = {'exists': 1,
                                    'write_file': 1,
                                    'create_directory': 1,
                                    'chown': 1,
                                    'chmod': 1}
            self.assert_build_log_file_name(expected_filename, log_file,
                                            os_mocks, expected_call_counts)

    def test_validate_log_file(self):
        file_name = '/tmp/non-existent-file'
        current_owner = getpass.getuser()
        with patch.multiple(operating_system,
                            exists=MagicMock(return_value=False),
                            write_file=DEFAULT,
                            chown=DEFAULT,
                            chmod=DEFAULT) as os_mocks:
            log_file = self.manager.validate_log_file(file_name, current_owner)
            assert_equal(file_name, log_file, "Unexpected filename")
            for key in os_mocks.keys():
                assert_true(os_mocks[key].call_count == 1,
                            "%s not called" % key)
