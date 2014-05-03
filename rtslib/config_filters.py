'''
This file is part of the LIO SCSI Target.

Copyright (c) 2012-2014 by Datera, Inc.
More information on www.datera.io.

Original author: Jerome Martin <jxm@netiant.com>

Datera and LIO are trademarks of Datera, Inc., which may be registered in some
jurisdictions.

Licensed under the Apache License, Version 2.0 (the "License"); you may
not use this file except in compliance with the License. You may obtain
a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.
'''
from config_tree import NO_VALUE

def get_composed_filter(*filters):
    '''
    Returns a node filter that is the composition of all filter functions
    passed as arguments. Filters will be applied in the order they appear.
    '''
    def composed_filter(node_in):
        for node_filter in filters:
            node_out = node_filter(node_in)
            if node_out is None:
                break
            else:
                node_in = node_out
        return node_out
    return composed_filter

def get_filter_on_type(allowed_types):
    '''
    Returns a node filter that only let nodes whose type is in the
    allowed_types list to pass through.
    '''
    def filter_on_type(node_in):
        if node_in.data['type'] in allowed_types:
            return node_in
    return filter_on_type

def get_reverse_filter(node_filter):
    '''
    Returns a new filter that lets throught all nodes normally filtered out by
    node_filter, and filters out the one normally passed.

    This should be useful only with filters that pass nodes through without
    modifying them.
    '''
    def reverse_filter(node_in):
        if node_filter(node_in) is None:
            return node_in
    return reverse_filter

def filter_no_default(node_in):
    '''
    A filter that lets all nodes through, except attributes with a default
    value and attribute groups containing only such attributes.
    '''
    node_out = node_in
    if node_in.data['type'] == 'attr' \
       and node_in.data['key'][1] != NO_VALUE \
       and node_in.data['key'][1] == node_in.data['val_dfl']:
            node_out = None
    elif node_in.data['type'] == 'group':
        node_out = None
        for attr in node_in.nodes:
            if filter_no_default(attr) is not None:
                node_out = node_in
                break
    return node_out

filter_only_default = get_reverse_filter(filter_no_default)

def filter_no_missing(node_in):
    '''
    A filter that lets all nodes through, except required attributes missing a
    value.
    '''
    node_out = node_in
    if node_in.data['type'] == 'attr' \
       and node_in.data['key'][1] is NO_VALUE:
        node_out = None
    return node_out

def filter_only_missing(node_in):
    '''
    A filter that only let through obj and groups containing attributes with
    missing values, as well as those attributes.
    '''
    # FIXME Breaks dump
    node_out = None
    if node_in.data['type'] == 'attr' \
       and node_in.data['key'][1] is NO_VALUE:
        node_out = node_in
    return node_out

def filter_only_required(node_in):
    '''
    A filter that only lets through required attribute nodes, aka those
    attributes without a default value in LIO configuration policy.
    '''
    if node_in.data['type'] == 'attr' \
       and node_in.data.get('val_dfl') is None:
        return node_in
