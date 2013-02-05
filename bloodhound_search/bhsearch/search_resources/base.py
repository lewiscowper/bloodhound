#!/usr/bin/env python
# -*- coding: UTF-8 -*-

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

r"""Base classes for Bloodhound Search plugin."""
from trac.core import Component
from trac.config import BoolOption

class BaseIndexer(Component):
    """
    This is base class for Bloodhound Search indexers of specific resource
    """
    silence_on_error = BoolOption('bhsearch', 'silence_on_error', "True",
        """If true, do not throw an exception during indexing a resource""")


class BaseSearchParticipant(Component):
    default_view = None
    default_grid_fields = None
    default_facets = None

    def get_default_facets(self):
        return self.default_facets

    def get_default_view(self):
        return self.default_view

    def get_default_view_fields(self, view):
        if view == "grid":
            return self.default_grid_fields
        return None
