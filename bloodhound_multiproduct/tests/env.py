
#  Licensed to the Apache Software Foundation (ASF) under one
#  or more contributor license agreements.  See the NOTICE file
#  distributed with this work for additional information
#  regarding copyright ownership.  The ASF licenses this file
#  to you under the Apache License, Version 2.0 (the
#  "License"); you may not use this file except in compliance
#  with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing,
#  software distributed under the License is distributed on an
#  "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
#  KIND, either express or implied.  See the License for the
#  specific language governing permissions and limitations
#  under the License.

"""Tests for Apache(TM) Bloodhound's product environments"""

from inspect import stack
import os.path
import shutil
from sqlite3 import OperationalError
import sys
import tempfile
from types import MethodType

if sys.version_info < (2, 7):
    import unittest2 as unittest
    from unittest2.case import _AssertRaisesContext
else:
    import unittest
    from unittest.case import _AssertRaisesContext

from trac.config import Option
from trac.core import Component
from trac.env import Environment
from trac.test import EnvironmentStub
from trac.tests.env import EnvironmentTestCase

from multiproduct.api import MultiProductSystem
from multiproduct.env import ProductEnvironment
from multiproduct.model import Product

# FIXME: Subclass TestCase explictly ?
class MultiproductTestCase(unittest.TestCase):
    r"""Mixin providing access to multi-product testing extensions.

    This class serves to the purpose of upgrading existing Trac test cases
    with multi-product super-powers while still providing the foundations
    to create product-specific subclasses.
    """

    # unittest2 extensions

    exceptFailureMessage = None

    class _AssertRaisesLoggingContext(_AssertRaisesContext):
        """Add logging capabilities to assertRaises
        """
        def __init__(self, expected, test_case, expected_regexp=None):
            _AssertRaisesContext.__init__(
                    self, expected, test_case, expected_regexp)
            self.test_case = test_case

        @staticmethod
        def _tb_locals(tb):
            if tb is None:
                # Inspect interpreter stack two levels up
                ns = stack()[2][0].f_locals.copy()
            else:
                # Traceback already in context
                ns = tb.tb_frame.f_locals.copy()
            ns.pop('__builtins__', None)
            return ns

        def __exit__(self, exc_type, exc_value, tb):
            try:
                return _AssertRaisesContext.__exit__(self, 
                    exc_type, exc_value, tb)
            except self.failureException, exc:
                msg = self.test_case.exceptFailureMessage 
                if msg is not None:
                    standardMsg = str(exc)
                    msg = msg % self._tb_locals(tb)
                    msg = self.test_case._formatMessage(msg, standardMsg)
                    raise self.failureException(msg)
                else:
                    raise
            finally:
                # Clear message placeholder
                self.test_case.exceptFailureMessage = None

    def assertRaises(self, excClass, callableObj=None, *args, **kwargs):
        """Adds logging capabilities on top of unittest2 implementation.
        """
        if callableObj is None:
            return self._AssertRaisesLoggingContext(excClass, self)
        else:
            return unittest.TestCase.assertRaises(
                    self, excClass, callableObj, *args, **kwargs)

    # Product data

    default_product = 'tp1'
    MAX_TEST_PRODUCT = 3

    PRODUCT_DATA = dict(
            ['tp' + str(i), {'prefix':'tp' + str(i),
                             'name' : 'test product ' + str(i),
                             'description' : 'desc for tp' + str(i)}]
            for i in xrange(1, MAX_TEST_PRODUCT)
        )

    # Test setup

    def _setup_test_env(self, create_folder=True, path=None):
        r"""Prepare a new test environment . 

        Optionally set its path to a meaningful location (temp folder
        if `path` is `None`).
        """
        self.env = env = EnvironmentStub(enable=['trac.*', 'multiproduct.*'])
        if create_folder:
            if path is None:
                env.path = tempfile.mkdtemp('bh-product-tempenv')
            else:
                env.path = path
        return env

    def _setup_test_log(self, env):
        r"""Ensure test product with prefix is loaded
        """
        logdir = tempfile.gettempdir()
        logpath = os.path.join(logdir, 'trac-testing.log')
        config = env.config
        config.set('logging', 'log_file', logpath)
        config.set('logging', 'log_type', 'file')
        config.set('logging', 'log_level', 'DEBUG')
        config.save()
        env.setup_log()
        env.log.info('%s test case: %s %s',
                '-' * 10, self.id(), '-' * 10)

    def _load_product_from_data(self, env, prefix):
        r"""Ensure test product with prefix is loaded
        """
        # TODO: Use fixtures implemented in #314
        product_data = self.PRODUCT_DATA[prefix]
        product = Product(env)
        product._data.update(product_data)
        product.insert()

    def _upgrade_mp(self, env):
        r"""Apply multi product upgrades
        """
        self.mpsystem = MultiProductSystem(env)
        try:
            self.mpsystem.upgrade_environment(env.db_transaction)
        except OperationalError:
            # table remains but database version is deleted
            pass

    def _mp_setup(self):
        """Shortcut for quick product-aware environment setup.
        """
        self.env = self._setup_test_env()
        self._upgrade_mp(self.env)
        self._setup_test_log(self.env)
        self._load_product_from_data(self.env, self.default_product)

class ProductEnvTestCase(EnvironmentTestCase, MultiproductTestCase):
    r"""Test cases for Trac environments rewritten for product environments
    """

    # Test setup

    def setUp(self):
        r"""Replace Trac environment with product environment
        """
        EnvironmentTestCase.setUp(self)
        try:
            self.global_env = self.env
            self._setup_test_log(self.global_env)
            self._upgrade_mp(self.global_env)
            self._load_product_from_data(self.global_env, self.default_product)
            try:
                self.env = ProductEnvironment(self.global_env, self.default_product)
            except :
                # All tests should fail if anything goes wrong
                self.global_env.log.exception('Error creating product environment')
                self.env = None
        except:
            shutil.rmtree(self.env.path)
            raise

    def tearDown(self):
        # Discard product environment
        self.env = self.global_env

        EnvironmentTestCase.tearDown(self)

class ProductEnvApiTestCase(MultiproductTestCase):
    """Assertions for Apache(TM) Bloodhound product-specific extensions in
    [https://issues.apache.org/bloodhound/wiki/Proposals/BEP-0003 BEP 3]
    """
    def setUp(self):
        self._mp_setup()
        self.product_env = ProductEnvironment(self.env, self.default_product)

    def test_attr_forward_parent(self):
        """Testing env.__getattr__"""
        class EnvironmentAttrSandbox(EnvironmentStub):
            """Limit the impact of class edits so as to avoid race conditions
            """

        self.longMessage = True

        class AttrSuccess(Exception):
            """Exception raised when target method / property is actually
            invoked.
            """

        def property_mock(attrnm, expected_self):
            def assertAttrFwd(instance):
                self.assertIs(instance, expected_self, 
                        "Mismatch in property '%s'" % (attrnm,))
                raise AttrSuccess
            return property(assertAttrFwd)

        self.env.__class__ = EnvironmentAttrSandbox
        try:
            for attrnm in 'system_info_providers secure_cookies ' \
                    'project_admin_trac_url get_system_info get_version ' \
                    'get_templates_dir get_templates_dir get_log_dir ' \
                    'backup'.split(): 
                original = getattr(Environment, attrnm)
                if isinstance(original, MethodType):
                    translation = getattr(self.product_env, attrnm)
                    self.assertIs(translation.im_self, self.env,
                            "'%s' not bound to global env in product env" % 
                                    (attrnm,))
                    self.assertIs(translation.im_func, original.im_func,
                            "'%s' function differs in product env" % (attrnm,))
                elif isinstance(original, (property, Option)):
                    # Intercept property access e.g. properties, Option, ...
                    setattr(self.env.__class__, attrnm, 
                        property_mock(attrnm, self.env))

                    self.exceptFailureMessage = 'Property %(attrnm)s'
                    with self.assertRaises(AttrSuccess) as cm_test_attr:
                        getattr(self.product_env, attrnm)
                else:
                    self.fail("Environment member %s has unexpected type" % 
                            (repr(original),))

        finally:
            self.env.__class__ = EnvironmentStub

        for attrnm in 'component_activated _component_rules ' \
                'enable_component get_known_users get_repository ' \
                '_component_name'.split():
            original = getattr(Environment, attrnm)
            if isinstance(original, MethodType):
                translation = getattr(self.product_env, attrnm)
                self.assertIs(translation.im_self, self.product_env,
                        "'%s' not bound to product env" % (attrnm,))
                self.assertIs(translation.im_func, original.im_func,
                        "'%s' function differs in product env" % (attrnm,))
            elif isinstance(original, property):
                translation = getattr(ProductEnvironment, attrnm)
                self.assertIs(original, translation,
                        "'%s' property differs in product env" % (attrnm,))

    def test_typecheck(self):
        """Testing env.__init__"""
        self._load_product_from_data(self.env, 'tp2')
        with self.assertRaises(TypeError) as cm_test:
            new_env = ProductEnvironment(self.product_env, 'tp2')

        msg = str(cm_test.exception)
        expected_msg = "Initializer must be called with " \
                "trac.env.Environment instance as first argument " \
                "(got multiproduct.env.ProductEnvironment instance instead)"
        self.assertEqual(msg, expected_msg)

    def test_component_enable(self):
        """Testing env.is_component_enabled"""
        class C(Component):
            pass
        # Let's pretend this was declared elsewhere
        C.__module__ = 'dummy_module'

        global_env = self.env
        product_env = self.product_env
        
        def clear_component_rules(env):
            del env._rules
            env.enabled.clear()

        # C initially disabled in both envs
        self.assertFalse(global_env.is_component_enabled(C))
        self.assertFalse(product_env.is_component_enabled_local(C))
        self.assertIs(global_env[C], None)
        self.assertIs(product_env[C], None)

        clear_component_rules(global_env)
        clear_component_rules(product_env)

        # C enabled in product env but not in global env
        product_env.enable_component(C)
        self.assertFalse(global_env.is_component_enabled(C))
        self.assertTrue(product_env.is_component_enabled_local(C))
        self.assertIs(global_env[C], None)
        self.assertIs(product_env[C], None)

        clear_component_rules(global_env)
        clear_component_rules(product_env)

        # C enabled in both envs
        product_env.enable_component(C)
        global_env.enable_component(C)
        self.assertTrue(global_env.is_component_enabled(C))
        self.assertTrue(product_env.is_component_enabled_local(C))
        self.assertIsNot(global_env[C], None)
        self.assertIsNot(product_env[C], None)

        clear_component_rules(global_env)
        clear_component_rules(product_env)

        # C enabled in global env but not in product env
        global_env.enable_component(C)
        self.assertTrue(global_env.is_component_enabled(C))
        self.assertFalse(product_env.is_component_enabled_local(C))
        self.assertIsNot(global_env[C], None)
        self.assertIs(product_env[C], None)

    def tearDown(self):
        # Release reference to transient environment mock object
        self.env = None
        self.product_env = None

def test_suite():
    return unittest.TestSuite([
            unittest.makeSuite(ProductEnvTestCase,'test'),
            unittest.makeSuite(ProductEnvApiTestCase, 'test')
        ])

if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
