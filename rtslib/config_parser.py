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
import logging
import pyparsing as pp

from config_tree import NO_VALUE

# TODO Add strategic debug (and logging too, it is absent)
# TODO Using group names as we do with obj_classes would be more robust

DEBUG = False
if DEBUG:
    logging.basicConfig()
    log = logging.getLogger('ConfigParser')
    log.setLevel(logging.DEBUG)
else:
    log = logging.getLogger('ConfigParser')
    log.setLevel(logging.INFO)

class ConfigParser(object):
    '''
    Our configuration format parser.
    '''
    # Order is important, used for sorting in Config
    obj_classes = "storage disk fabric target tpgt lun acl portal mapped_lun"

    def __init__(self):
        self._init_parser()

    def _init_parser(self):
        pp.ParserElement.setDefaultWhitespaceChars(' \t')

        tok_comment = pp.Regex(r'#.*')
        tok_ws = pp.Suppress(pp.OneOrMore(pp.White(' \t')))
        tok_delim = (pp.Optional(pp.Suppress(tok_comment))
                     + pp.Suppress(pp.lineEnd | pp.Literal(';')))

        tok_string = (pp.QuotedString('"')
                      | pp.QuotedString("'")
                      | pp.Word(pp.printables, excludeChars="{}#'\";"))

        tok_obj_class = pp.oneOf(self.obj_classes)
        tok_obj_ident = tok_string
        tok_obj = pp.Group(tok_obj_class
                           + tok_ws
                           + tok_obj_ident)
        tok_obj = tok_obj.setParseAction(self._parse_action_obj)

        tok_attr_name = pp.Word(pp.alphas, pp.alphas + pp.nums + "_")
        tok_attr_value = tok_string
        tok_attr = pp.Group(tok_attr_name
                            + tok_ws
                            + tok_attr_value
                            + pp.Optional(tok_comment))
        tok_attr = tok_attr.setParseAction(self._parse_action_attr)

        tok_group = pp.Word(pp.alphas, pp.alphas + "_") 
        tok_group = tok_group.setParseAction(self._parse_action_group)

        # FIXME This does not work as intended when used
        # tok_empty_block = pp.Suppress('{' + pp.ZeroOrMore(tok_delim) + '}')

        tok_statement = pp.Forward()
        tok_block = (pp.Group(pp.Suppress('{')
                              + pp.OneOrMore(tok_statement)
                              + pp.Suppress('}')))
        tok_block = tok_block.setParseAction(self._parse_action_block)

        tok_statement_no_path = ((tok_group + tok_ws + tok_attr)
                                 #| (tok_group + tok_empty_block)
                                 | (tok_group + tok_block)
                                 | tok_attr)

        tok_optional_if_path = ((tok_ws + tok_group + tok_ws + tok_attr)
                                #| (tok_ws + tok_group + tok_empty_block)
                                | (tok_ws + tok_group + tok_block)
                                #| tok_empty_block
                                | tok_block
                                | (tok_ws + tok_attr))

        tok_statement_if_path = (pp.OneOrMore(tok_obj)
                                 + pp.Optional(tok_optional_if_path))

        tok_statement << pp.Group(pp.ZeroOrMore(tok_delim)
                                  + (tok_statement_if_path
                                     | tok_statement_no_path)
                                  + pp.OneOrMore(tok_delim))

        self._parser = pp.ZeroOrMore(tok_statement)

    def _parse_action_obj(self, source, idx, tokin):
        value = tokin[0]
        return [{'type': 'obj',
                 'line': pp.lineno(idx, source),
                 'col': pp.col(idx, source),
                 'key': (value[0], value[1])}]

    def _parse_action_attr(self, source, idx, tokin):
        value = tokin[0]
        tokout = {'type': 'attr',
                  'line': pp.lineno(idx, source),
                  'col': pp.col(idx, source),
                  'key': (value[0], value[1])}
        if len(value) > 2:
            tokout['comment'] = value[2][1:].strip()
        return [tokout]

    def _parse_action_group(self, source, idx, tokin):
        value = tokin
        return [{'type': 'group',
                 'line': pp.lineno(idx, source),
                 'col': pp.col(idx, source),
                 'key': (value[0],)}]

    def _parse_action_block(self, source, idx, tokin):
        value = tokin[0].asList()
        return [{'type': 'block',
                 'line': pp.lineno(idx, source),
                 'col': pp.col(idx, source),
                 'statements': value}]

    def parse_file(self, filepath):
        return self._parser.parseFile(filepath, parseAll=True).asList()

    def parse_string(self, string):
        return self._parser.parseString(string, parseAll=True).asList()

class PolicyParser(ConfigParser):
    '''
    Our policy format parser.
    '''
    def _init_parser(self):
        # TODO Once stable, factorize with ConfigParser
        pp.ParserElement.setDefaultWhitespaceChars(' \t')

        tok_comment = pp.Regex(r'#.*')
        tok_ws = pp.Suppress(pp.OneOrMore(pp.White(' \t')))
        tok_delim = (pp.Optional(pp.Suppress(tok_comment))
                     + pp.Suppress(pp.lineEnd | pp.Literal(';')))

        tok_string = (pp.QuotedString('"')
                      | pp.QuotedString("'")
                      | pp.Word(pp.printables, excludeChars="{}#'\";%@()"))

        tok_ref_path = (pp.Suppress('@') + pp.Suppress('(')
                        + pp.OneOrMore(tok_string)
                        + pp.Suppress(')'))

        tok_id_rule = pp.Suppress('%') + tok_string("id_type")

        tok_val_rule = (pp.Suppress('%')
                        + tok_string("val_type")
                        + pp.Optional(pp.Suppress('(')
                                      + tok_string("val_dfl")
                                      + pp.Suppress(')')))

        tok_obj_class = pp.oneOf(self.obj_classes)
        tok_obj_ident = tok_id_rule | tok_string("id_fixed")
        tok_obj = pp.Group(tok_obj_class("class")
                           + tok_ws
                           + tok_obj_ident)
        tok_obj = tok_obj.setParseAction(self._parse_action_obj)

        tok_attr_name = pp.Word(pp.alphas, pp.alphas + pp.nums + "_")
        tok_attr_value = tok_ref_path("ref_path") | tok_val_rule
        tok_attr = pp.Group(tok_attr_name("name")
                            + tok_ws
                            + tok_attr_value
                            + pp.Optional(tok_comment)("comment"))
        tok_attr = tok_attr.setParseAction(self._parse_action_attr)

        tok_group = pp.Word(pp.alphas, pp.alphas + "_") 
        tok_group = tok_group.setParseAction(self._parse_action_group)

        tok_statement = pp.Forward()
        tok_block = (pp.Group(pp.Suppress('{')
                              + pp.OneOrMore(tok_statement)
                              + pp.Suppress('}')))
        tok_block = tok_block.setParseAction(self._parse_action_block)

        tok_statement_no_path = ((tok_group + tok_ws + tok_attr)
                                 | (tok_group + tok_block)
                                 | tok_attr)

        tok_optional_if_path = ((tok_ws + tok_group + tok_ws + tok_attr)
                                | (tok_ws + tok_group + tok_block)
                                | tok_block
                                | (tok_ws + tok_attr))

        tok_statement_if_path = (pp.OneOrMore(tok_obj)
                                 + pp.Optional(tok_optional_if_path))

        tok_statement << pp.Group(pp.ZeroOrMore(tok_delim)
                                  + (tok_statement_if_path
                                     | tok_statement_no_path)
                                  + pp.OneOrMore(tok_delim))

        self._parser = pp.ZeroOrMore(tok_statement)

    def _parse_action_attr(self, source, idx, tokin):
        value = tokin[0].asDict()
        ref_path = value.get('ref_path')
        if ref_path is not None:
            ref_path = " ".join(ref_path.asList())
        tokout = {'type': 'attr',
                  'line': pp.lineno(idx, source),
                  'col': pp.col(idx, source),
                  'ref_path': ref_path,
                  'val_type': value.get('val_type'),
                  'val_dfl': value.get('val_dfl', NO_VALUE),
                  'required': value.get('val_dfl', NO_VALUE) == NO_VALUE,
                  'comment': value.get('comment'),
                  'key': (value.get('name'), 'xxx')}

        return [tokout]

    def _parse_action_obj(self, source, idx, tokin):
        value = tokin[0].asDict()
        return [{'type': 'obj',
                 'line': pp.lineno(idx, source),
                 'col': pp.col(idx, source),
                 'id_type': value.get('id_type'),
                 'id_fixed': value.get('id_fixed'),
                 'key': (value.get('class'), value.get('id_fixed', 'xxx'))}]

class PatternParser(ConfigParser):
    '''
    Our pattern format parser.
    '''
    def _init_parser(self):
        # TODO Once stable, factorize with ConfigParser
        pp.ParserElement.setDefaultWhitespaceChars(' \t')

        tok_ws = pp.Suppress(pp.OneOrMore(pp.White(' \t')))

        tok_string = (pp.QuotedString('"')
                      | pp.QuotedString("'")
                      | pp.Word(pp.printables, excludeChars="{}#'\";"))

        tok_obj_class = pp.oneOf(self.obj_classes)
        tok_obj_ident = tok_string
        tok_obj = pp.Group(tok_obj_class + tok_ws + tok_obj_ident)
        tok_obj = tok_obj.setParseAction(self._parse_action_obj_attr)

        tok_attr_name = pp.Word(pp.alphas + pp.nums + "_.*[]-")
        tok_attr_value = tok_string
        tok_attr = pp.Group(tok_attr_name + tok_ws + tok_attr_value)
        tok_attr = tok_attr.setParseAction(self._parse_action_obj_attr)

        tok_group = pp.Word(pp.alphas + "_.*[]-") 
        tok_group = tok_group.setParseAction(self._parse_action_group)

        tok_statement_no_path = ((tok_group + tok_ws + tok_attr)
                                 | tok_attr
                                 | tok_group)

        tok_optional_if_path = ((tok_ws + tok_group + tok_ws + tok_attr)
                                | (tok_ws + tok_attr)
                                | (tok_ws + tok_group))

        tok_statement_if_path = (pp.OneOrMore(tok_obj)
                                 + pp.Optional(tok_optional_if_path))

        self._parser = tok_statement_if_path | tok_statement_no_path

    def _parse_action_obj_attr(self, source, idx, tokin):
        return (tokin[0][0], tokin[0][1])

    def _parse_action_group(self, source, idx, tokin):
        return (tokin[0],)
