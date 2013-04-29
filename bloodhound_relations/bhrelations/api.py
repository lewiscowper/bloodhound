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
from copy import copy
from bhrelations import db_default
from bhrelations.model import Relation
from multiproduct.env import ProductEnvironment
from trac.core import Component, implements, TracError
from trac.env import IEnvironmentSetupParticipant
from trac.db import DatabaseManager
from trac.resource import (manager_for_neighborhood, ResourceSystem, Resource,
                           get_resource_shortname)
from trac.ticket import Ticket

PLUGIN_NAME = 'Bloodhound Relations Plugin'

class ValidationError(TracError):
    pass

class EnvironmentSetup(Component):
    implements(IEnvironmentSetupParticipant)

    def environment_created(self):
        self.found_db_version = 0
        self.upgrade_environment(self.env.db_transaction)

    def environment_needs_upgrade(self, db):
        """Detects if the installed db version matches the running system"""
        db_installed_version = self._get_version()

        db_version = db_default.DB_VERSION
        if db_installed_version > db_version:
            raise TracError('''Current db version (%d) newer than supported by
            this version of the %s (%d).''' % (db_installed_version,
                                               PLUGIN_NAME,
                                               db_version))
        needs_upgrade = db_installed_version < db_version
        return needs_upgrade

    def upgrade_environment(self, db):
        self.log.debug("upgrading existing environment for %s plugin." %
                       PLUGIN_NAME)
        db_installed_version = self._get_version()
        with self.env.db_direct_transaction as db:
            if db_installed_version < 1:
                self._initialize_db(db)
                self._update_db_version(db, 1)
            #add upgrade logic later if needed

    def _get_version(self):
        """Finds the current version of the bloodhound database schema"""
        rows = self.env.db_direct_query("""
            SELECT value FROM system WHERE name = %s
            """, (db_default.DB_SYSTEM_KEY,))
        return int(rows[0][0]) if rows else -1

    def _update_db_version(self, db, version):
        old_version = self._get_version()
        if old_version != -1:
            self.log.info(
                "Updating %s database schema from version %d to %d",
                PLUGIN_NAME, old_version, version)
            db("""UPDATE system SET value=%s
                      WHERE name=%s""", (version, db_default.DB_SYSTEM_KEY))
        else:
            self.log.info(
                "Initial %s database schema set to version %d",
                PLUGIN_NAME, version)
            db("""
                INSERT INTO system (name, value) VALUES ('%s','%s')
                """  % (db_default.DB_SYSTEM_KEY, version))
        return version

    def _initialize_db(self, db):
        self.log.debug("creating initial db schema for %s.", PLUGIN_NAME)
        db_connector, dummy = DatabaseManager(self.env)._get_connector()
        for table in db_default.SCHEMA:
            for statement in db_connector.to_sql(table):
                db(statement)


class RelationsSystem(Component):
    PARENT_RELATION_TYPE = 'parent'
    RELATIONS_CONFIG_NAME = 'bhrelations_links'
    RESOURCE_ID_DELIMITER = u":"
    RELATION_ID_DELIMITER = u","

    def __init__(self):
        self._links, self._labels, \
        self._validators, self._blockers, \
        self._copy_fields = self._get_links_config()

        self.link_ends_map = {}
        for end1, end2 in self.get_ends():
            self.link_ends_map[end1] = end2
            if end2 is not None:
                self.link_ends_map[end2] = end1

    def get_ends(self):
        return self._links

    def add(
            self,
            source_resource_instance,
            destination_resource_instance,
            relation_type,
            comment = None,
            ):
        source = self.get_resource_id_from_instance(source_resource_instance)
        destination = self.get_resource_id_from_instance(
            destination_resource_instance)
        relation = Relation(self.env)
        relation.source = source
        relation.destination = destination
        relation.type = relation_type
        relation.comment = comment
        self.add_relation(relation)

    def add_relation(self, relation):
        self.validate(relation)
        #TBD: add changes in source and destination ticket history
        with self.env.db_transaction:
            relation.insert()
            other_end = self.link_ends_map[relation.type]
            if other_end:
                reverted_relation = relation.clone_reverted(other_end)
                reverted_relation.insert()

    def delete(
            self,
            relation_id,
        ):
        source, destination, relation_type = self._parse_relation_id(
            relation_id)
        #TODO: some optimization can be introduced here to not load relations
        #before actual DELETE SQL
        relation = Relation(self.env, keys=dict(
            source=source,
            destination=destination,
            type=relation_type
            ))
        self._delete_relation(relation)

    def _delete_relation(self, relation):
        source = relation.source
        destination = relation.destination
        relation_type = relation.type
        with self.env.db_transaction:
            relation.delete()
            other_end = self.link_ends_map[relation_type]
            if other_end:
                reverted_relation = Relation(self.env, keys=dict(
                    source=destination,
                    destination=source,
                    type=other_end,
                ))
                reverted_relation.delete()

    def _debug_select(self):
        """The method is used for debug purposes"""
        sql = "SELECT id, source, destination, type FROM bloodhound_relations"
        with self.env.db_query as db:
            return [db(sql)]

    def get_relations(self, resource_instance):
        relation_list = []
        for relation in self._select_relations_for_resource(resource_instance):
            relation_list.append(dict(
                relation_id = self._create_relation_id(relation),
                destination_id = relation.destination,
                destination=self._create_resource_instance_by_full_id(
                    relation.destination),
                type = relation.type,
                comment = relation.comment
            ))
        return relation_list

    def _select_relations_for_resource(self, resource, resource_type=None):
        source = self.get_resource_id_from_instance(resource)
        return self._select_relations_by_source(source, resource_type)

    def _select_relations_by_source(
            self, source, resource_type=None):
        #todo: add optional paging for possible umbrella tickets with
        #a lot of child tickets
        where = dict(source=source)
        if resource_type:
            where["type"]=resource_type
            order_by=["destination"]
        else:
            order_by=["type", "destination"]
        return Relation.select(
            self.env,
            where=where,
            order_by=order_by
            )

    def _create_relation_id(self, relation):
        return self.RELATION_ID_DELIMITER.join((
            relation.source,
            relation.destination,
            relation.type))

    def _parse_relation_id(self, relation_id):
        source, destination, relation_type = relation_id.split(
            self.RELATION_ID_DELIMITER)
        return source, destination, relation_type

    # Copied from trac/ticket/links.py, ticket-links-trunk branch
    def _get_links_config(self):
        links = []
        labels = {}
        validators = {}
        blockers = {}
        copy_fields = {}

        config = self.config[self.RELATIONS_CONFIG_NAME]
        for name in [option for option, _ in config.options()
                     if '.' not in option]:
            ends = [e.strip() for e in config.get(name).split(',')]
            if not ends:
                continue
            end1 = ends[0]
            end2 = None
            if len(ends) > 1:
                end2 = ends[1]
            links.append((end1, end2))

            label1 = config.get(end1 + '.label') or end1.capitalize()
            labels[end1] = label1
            if end2:
                label2 = config.get(end2 + '.label') or end2.capitalize()
                labels[end2] = label2

            validator = config.get(name + '.validator')
            if validator:
                validators[end1] = validator
                if end2:
                    validators[end2] = validator

            blockers[end1] = config.getbool(end1 + '.blocks', default=False)
            if end2:
                blockers[end2] = config.getbool(end2 + '.blocks', default=False)

            # <end>.copy_fields may be absent or intentionally set empty.
            # config.getlist() will return [] in either case, so check that
            # the key is present before assigning the value
            for end in [end1, end2]:
                if end:
                    cf_key = '%s.copy_fields' % end
                    if cf_key in config:
                        copy_fields[end] = config.getlist(cf_key)

        return links, labels, validators, blockers, copy_fields

    def get_resource_id_from_instance(self, resource_instance):
        resource = resource_instance.resource
        rsys = ResourceSystem(manager_for_neighborhood(
            self.env, resource.neighborhood))
        nbhprefix = rsys.neighborhood_prefix(resource.neighborhood)
        resource_full_id = self.RESOURCE_ID_DELIMITER.join(
            (nbhprefix, resource.realm, unicode(resource.id))
        )
        return resource_full_id

    def _create_resource_instance_by_full_id(self, resource_full_id):
        """
        * resource_full_id: fully qualified resource id in format
        "product:ticket:123". In case of global environment it is ":ticket:123"
        """
        nbhprefix, realm, resource_id = self.split_full_id(resource_full_id)
        return self._create_resource_by_ids(nbhprefix, realm, resource_id)

    def _get_resource_by_id(self, resource_full_id):
        """
        * resource_full_id: fully qualified resource id in format
        "product:ticket:123". In case of global environment it is ":ticket:123"
        """
        nbhprefix, realm, resource_id = self.split_full_id(resource_full_id)
        env = self._get_env_by_prefix(nbhprefix)
        return Resource(env, realm, resource_id)


    def _create_resource_by_ids(self, nbhprefix, realm, resource_id):
        env = self._get_env_by_prefix(nbhprefix)
        #todo: implement more generic resource factory mechanism
        if realm == "ticket":
            return Ticket(env, resource_id)
        else:
            raise TracError("Resource type %s is not supported by " +
                            "Bloodhound Relations" % realm)

    def _get_env_by_prefix(self, nbhprefix):
        if nbhprefix:
            env = ProductEnvironment(nbhprefix)
        elif hasattr(self.env, "parent") and self.env.parent:
            env = self.env.parent
        else:
            env = self.env
        return env


    def validate(self, relation):
        validator = self._get_validator(relation.type)
        result = validator(relation)
        if result is not None:
            raise ValidationError(result)

    # Copied from trac/utils.py, ticket-links-trunk branch
    def unique(self, seq):
        """Yield unique elements from sequence of hashables, preserving order.
        (New in 0.13)
        """
        seen = set()
        return (x for x in seq if x not in seen and not seen.add(x))

    def can_be_resolved(self, resource):
        #todo: implement the method
        # blockers = []
        for relation in self._select_relations_for_resource(resource):
            if self.is_blocker(relation.type):
                blockers = self.find_blockers(relation)
                if blockers:
                    blockers_str = ', '.join('#%s' % x
                                             for x in self.unique(blockers))
                    msg = ("Cannot resolve this ticket because it is "
                           "blocked by '%s' tickets [%s]"
                           % (end,  blockers_str))
                    yield None, msg

    def is_blocker(self, relation_type):
        return self._blockers[relation_type]

    def _get_validator(self, relation_type):
        #todo: implement generic validator factory based on interfaces
        validator_name = self._validators.get(relation_type)
        if validator_name == 'no_cycle':
            validator = self._validate_no_cycle
        elif validator_name == 'parent_child' and \
                        relation_type == self.PARENT_RELATION_TYPE:
            validator = self._validate_parent
        else:
            validator = self._validate_any
        return validator

    def _validate_no_cycle(self, relation):
        cycle = self._find_cycle(relation.source, relation, [])
        if cycle != None:
            cycle_str = [self._get_resource_name_from_id(resource_id)
                         for resource_id in cycle]
            return 'Cycle in ''%s'': %s' % (
                self.render_relation_type(relation.type),
                ' -> '.join(cycle_str))

    def _validate_parent(self, relation):
        cycle_validation = self._validate_no_cycle(relation)
        if cycle_validation:
            return cycle_validation

        if relation.type == self.PARENT_RELATION_TYPE:
            parent_relations = self._select_relations_by_source(
                relation.source, relation.type)
            if len(parent_relations):
                source_resource_name = self._get_resource_name_from_id(
                    relation.source)
                parent_ids_ins_string = ", ".join(
                    [self._get_resource_name_from_id(relation.destination)
                     for relation in parent_relations]
                )
                return "Multiple links in '%s': #%s -> [%s]" % (
                    self.render_relation_type(relation.type),
                    source_resource_name,
                    parent_ids_ins_string)

    def _get_resource_name_from_id(self, resource_id):
        resource = self._get_resource_by_id(resource_id)
        return get_resource_shortname(self.env, resource)

    def _validate_any(self, relation):
        return None

    def _find_cycle(self, source_to_check, relation, path):
        #todo: optimize this
        destination = relation.destination
        if source_to_check == destination:
            path.append(destination)
            return path
        path.append(destination)
        relations = Relation.select(
            self.env,
            where=dict(source=destination, type=relation.type),
            order_by=["destination"]
            )
        for linked_relation in relations:
            cycle = self._find_cycle(
                source_to_check, linked_relation, copy(path))
            if cycle is not None:
                return cycle
        return None

    def render_relation_type(self, end):
        return self._labels[end]

    def find_blockers(self, relation, blockers):
        #todo: optimize performance by possibility to select more
        # source ids at once
        for linked_relation in self._select_relations_by_source(
                relation.destination):
            resource_instance = self._create_resource_instance_by_full_id(
                linked_relation.destination)
            if self._is_resource_blocked(resource_instance):
                blockers.append(resource_instance)
            else:
                self.find_blockers(linked_relation, blockers)
        return blockers

    def split_full_id(self, resource_full_id):
        return resource_full_id.split(self.RESOURCE_ID_DELIMITER)

    def _is_resource_blocked(self, resource_instance):
        #todo: implement more generic blocker validation
        realm = resource_instance.resource.realm
        if realm == "ticket":
            ticket = resource_instance
            return ticket['status'] != 'closed'
        else:
            raise TracError("Block validation for type %s is not supported" +
                        " by Bloodhound Relations" % realm)




