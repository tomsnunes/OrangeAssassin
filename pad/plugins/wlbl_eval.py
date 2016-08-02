""" WLBLEval plugin."""
from __future__ import absolute_import

import re
from collections import defaultdict

import dns
import ipaddress

import pad.plugins.base
from pad.networks import _format_network_str


FROM_HEADERS = ('From', "Envelope-Sender", 'Resent-From', 'X-Envelope-From', 'EnvelopeFrom')
TO_HEADERS = ('To', 'Resent-To', 'Resent-Cc', 'Apparently-To', 'Delivered-To',
              'Envelope-Recipients', 'Apparently-Resent-To', 'X-Envelope-To',
              'Envelope-To',
              'X-Delivered-To', 'X-Original-To', 'X-Rcpt-To', 'X-Real-To',
              'Cc')
TL_TLDS = ['.com', '.co.uk']


class WLBLEvalPlugin(pad.plugins.base.BasePlugin):
    eval_rules = ("check_from_in_whitelist", "check_to_in_whitelist",
                  "check_from_in_blacklist", "check_to_in_blacklist",
                  "check_from_in_list", "check_to_in_all_spam",
                  "check_to_in_list", "check_mailfrom_matches_rcvd",
                  "check_from_in_default_whitelist",
                  "check_forged_in_whitelist",
                  "check_to_in_more_spam", "check_forged_in_default_whitelist",
                  "check_uri_host_listed", "check_uri_host_in_whitelist",
                  "check_uri_host_in_blacklist"
                  )
    options = {
        "blacklist_from": ("list", []),
        "whitelist_from": ("list", []),
        "whitelist_to": ("list", []),
        "blacklist_to": ("list", []),
        "all_spam_to": ("list", []),
        "more_spam_to list": ("list", []),
        "def_whitelist_from_rcvd": ("list", []),
        "whitelist_from_rcvd": ("list", []),
        "whitelist_allow_relays": ("list", []),
        "enlist_uri_host": ("list", []),
        "delist_uri_host": ("list", []),
        "blacklist_uri_host": ("list", []),
        "whitelist_uri_host": ("list", [])
    }

    parsed_lists = {
        "parsed_blacklist_from": ("dict", {}),
        "parsed_whitelist_from": ("dict", {}),
        "parsed_whitelist_to": ("dict", {}),
        "parsed_blacklist_to": ("dict", {}),
        "parsed_all_spam_to": ("dict", {}),
        "parsed_more_spam_to list": ("dict", {}),
        "parsed_def_whitelist_from_rcvd": ("dict", {}),
        "parsed_whiparsed_telist_from_rcvd": ("dict", {}),
        "parsed_whitelist_allow_relays": ("dict", {}),
        "parsed_enlist_uri_host": ("dict", {}),
        "parsed_delist_uri_host": ("dict", {}),
        "parsed_whitelist_uri_host": ("dict", {}),
        "parsed_blacklist_uri_host": ("dict", {})
    }

    def check_start(self, msg):
        """Parses all the required white and blacklists. Stores
        the results in the the "parsed" versions.
        """
        self['parsed_whitelist_from'] = self.parse_list('whitelist_from')
        self['parsed_whitelist_to'] = self.parse_list('whitelist_to')
        self['parsed_blacklist_from'] = self.parse_list('blacklist_from')
        self['parsed_blacklist_to'] = self.parse_list('blacklist_to')
        self['parsed_all_spam_to'] = self.parse_list('all_spam_to')
        self['parsed_more_spam_to list'] = self.parse_list('more_spam_to list')
        self['parsed_def_whitelist_from_rcvd'] = self.parse_list(
            'def_whitelist_from_rcvd')
        self['parsed_whitelist_from_rcvd'] = self.parse_list(
            'whitelist_from_rcvd')
        self['parsed_whitelist_allow_relays'] = self.parse_list(
            'whitelist_allow_relays')
        self["parsed_delist_uri_host"] = self.parse_delist_uri()
        self['parsed_enlist_uri_host'] = self.parse_list_uri('enlist_uri_host')

    def parse_list(self, list_name):
        """Parse the list into a dictionary with the regex as key and the domain as value.
        """
        parsed_list = defaultdict(list)
        for x in self[list_name]:
            parsed_list[x.split()[0]].append(x.split()[1])
        return parsed_list

    def my_list(self):
        return {"in_list": [], "not_in_list": []}

    def parse_delist_uri(self):
        parsed_list = defaultdict(list)
        for x in self['delist_uri_host']:
            uri_host_list = x.split()
            if "(" in x:
                key = uri_host_list[0].strip("( ").rstrip(" )")
                parsed_list[key].extend(uri_host_list[1:])
            else:
                parsed_list['ALL'].extend(uri_host_list)
        return parsed_list

    def add_in_list(self, key, item, parsed_list):
        """Add elements in parsed list
        """
        if item.startswith("!"):
            parsed_list[key]["not_in_list"].append(item.strip("!"))
        else:
            parsed_list[key]["in_list"].append("." + item)
        return parsed_list

    def add_in_dict(self, list_name, key, parsed_list):
        """Add elements in the parsed list dictionary and ignore
        the ones that are in the 'delist_uri_host' """
        delist = self['parsed_delist_uri_host']
        for item in list_name:
            if item in delist[key] or item in delist['ALL']:
                continue
            self.add_in_list(key, item, parsed_list)
        return parsed_list

    def parse_list_uri(self, list_name):
        parsed_list = defaultdict(self.my_list)
        for x in self[list_name]:
            uri_host_list = x.split()
            key = uri_host_list[0].strip("( ").rstrip(" )")
            self.add_in_dict(uri_host_list[1:], key, parsed_list)

        self.add_in_dict(self['whitelist_uri_host'], 'WHITE',
                         parsed_list)
        self.add_in_dict(self['blacklist_uri_host'], 'BLACK',
                         parsed_list)
        return parsed_list

    def check_in_list(self, msg, addresses, list_name, param):
        for address in addresses:
            for regex in self[list_name]:
                if re.search(regex.replace("*", ".*"), address):
                    self.set_local(msg, param, 1)
                    return True
            wh = self.check_whitelist_rcvd(msg, list_name, None)
            if wh == 1:
                self.set_local(msg, param, 1)
                return True
            elif wh == -1:
                self.set_local(msg, param, -1)
        return False

    def check_address_in_list(self, addresses, list_name):
        """Check if addresses match the regexes from list_name.
        """
        for address in addresses:
            for regex in self[list_name]:
                if re.search(regex.replace("*", ".*"), address):
                    return True
        return False

    def check_in_default_whitelist(self, msg, addresses, list_name, param):
        for address in addresses:
            wh = self.check_whitelist_rcvd(msg, list_name, None)
            if wh == 1:
                self.set_local(msg, param, 1)
                return True
            elif wh == -1:
                self.set_local(msg, param, -1)
        return False

    def get_from_addresses(self, msg):
        """Get addresses from 'Resent-From' header,
        and if there are no addresses, get from
        all FROM_HEADERS.
        """
        addresses = msg.get_addr_header('Resent-From')
        if addresses:
            for address in addresses:
                yield address
        else:
            for key in FROM_HEADERS:
                for address in msg.get_addr_header(key):
                    yield address

    def get_to_addresses(self, msg):
        """Get addresses from 'Resent-To' and 'Resent-Cc'
        headers, ad if there are no addresses, get from
        all TO_HEADERS.
        """
        addresses = msg.get_addr_header('Resent-To')
        addresses.extend(msg.get_addr_header('Resent-Cc'))
        if addresses:
            for address in addresses:
                yield address
        else:
            for key in TO_HEADERS:
                for address in msg.get_addr_header(key):
                    yield address

    def base_domain(self, address):
        domain = address
        parts = domain.split('.')
        if len(parts) < 3:
            return ".".join(parts)
        if len([p for p in parts if not p.isdigit()]) == 0:
            # Handle numeric IPs in URIs similarly, but reverse the octet
            # ordering before comparison against the RBL. For example,
            # http://10.20.30.40/ is checked as 40.30.20.10.multi.surbl.org.
            return ".".join(parts[::-1])
        if ".".join(parts[-3:]) in TL_TLDS:
            return ".".join(parts[-4:])
        if ".".join(parts[-2:]) in TL_TLDS:
            return ".".join(parts[-3:])
        return ".".join(parts[-2:])

    def check_from_in_whitelist(self, msg, target=None):
        """Get all the from addresses with get_from_addresses and
        check if they match the whitelist regexes.
        """
        return self._check_whitelist(msg, "from_in_whitelist")

    def _check_whitelist(self, msg, check_name):
        addresses = self.get_from_addresses(msg)
        list_name = 'parsed_whitelist_from'
        if self.get_local(msg, check_name) == 0:
            exists = self.check_in_list(msg, addresses, list_name,
                                        check_name)
        return self.get_local(msg, check_name) > 0

    def check_to_in_whitelist(self, msg, target=None):
        """Get all the to addresses with get_to_addresses and
        check if they match the whitelist regexes.
        """
        return self.check_address_in_list(self.get_to_addresses(msg),
                                          'parsed_whitelist_to')

    def check_from_in_blacklist(self, msg, target=None):
        """Get all the from addresses and
        check if they match the blacklist regexes.
        """
        return self.check_address_in_list(self.get_from_addresses(msg),
                                          'parsed_blacklist_from')

    def check_to_in_blacklist(self, msg, target=None):
        """Get all the from addresses and
        check if they match the blacklist regexes.
        """
        return self.check_address_in_list(self.get_to_addresses(msg),
                                          'parsed_blacklist_to')

    def check_from_in_list(self, msg, list_name, target=None):
        """Get all the from addresses with and
        check if they match the given list regexes.
        """
        if not list_name:
            return False
        return self.check_address_in_list(self.get_from_addresses(msg),
                                          list_name)

    def check_to_in_list(self, msg, list_name, target=None):
        """Get all the to addresses and check if they match
        the given list regexes.
        """
        if not list_name:
            return False
        return self.check_address_in_list(self.get_to_addresses(msg),
                                          list_name)

    # done
    def check_to_in_all_spam(self, msg, target=None):
        """Get all the to addresses and check if they match
        the 'all_spam_to' regexes.
        """
        return self.check_address_in_list(self.get_to_addresses(msg),
                                          'parsed_all_spam_to')

    # done
    def check_to_in_more_spam(self, msg, target=None):
        """Get all the to addresses and check if they match
        the 'more_spam_to_list' regexes.
        """
        return self.check_address_in_list(self.get_to_addresses(msg),
                                          'parsed_more_spam_to list')

    def check_from_in_default_whitelist(self, msg, target=None):
        """Get all the from addresses and check if they match
        the 'from_in_default_whitelist' regexes.
        """
        return self._check_whitelist(msg, "from_in_default_whitelist")

    def check_mailfrom_matches_rcvd(self, msg, target=None):
        """ If there is an EnvelopeFrom address, get it's domain.
        If there are untrusted relays, get the first one,
        else if there are trusted relays get them all.
        For each non empty relay rdns verify if the last part
        of the domain matches the last part of the rdns.
        """
        address = msg.sender_address
        relays = []
        if address:
            domain = self.base_domain(address.split("@")[1])
        else:
            return False
        if len(msg.untrusted_relays) > 0:
            relays.append(msg.untrusted_relays[0])
        elif len(msg.trusted_relays) > 0:
            relays.extend(msg.trusted_relays)
        else:
            return False
        for relay in relays:
            ip = ipaddress.ip_address(relay['ip']).exploded
            reversed_ip = str(dns.reversename.from_address(ip))
            parts = reversed_ip.rsplit(".", 2)
            ip = parts.pop(0)
            relay_domain = ".".join(parts)
            if relay_domain == domain:
                return True
        return False

    def check_forged_in_whitelist(self, msg, target=None):
        self.check_from_in_whitelist(msg)
        self.check_from_in_default_whitelist(msg)
        checked_w = (self.get_local(msg, "from_in_whitelist") < 0)
        checked_dw = (self.get_local(msg, "from_in_default_whitelist") == 0)
        return checked_w and checked_dw

    check_forged_in_default_whitelist = check_forged_in_whitelist

    def check_whitelist_rcvd(self, msg, list_name, target=None):
        if len(msg.untrusted_relays) + len(msg.trusted_relays) < 0:
            return 0
        relays = []
        if len(msg.untrusted_relays) > 0:
            relays = msg.untrusted_relays[0]
        elif len(msg.trusted_relays) > 0:
            relays.extend(msg.trusted_relays)

        address = msg.sender_address.lower()
        found_forged = 0
        for white_addr in self[list_name]:
            regexp = white_addr.replace("*", ".*")
            for domain in self[list_name][white_addr]:
                if re.search(regexp, address):
                    match = self.check_rcvd(domain, match, relays)
                    if match:
                        return 1
                    found_forged = -1
        found_forged = self.check_found_forged(address, found_forged)
        return found_forged

    def check_rcvd(self, domain, match, relays):
        for relay in relays:
            # extract the string between "[ ... ]"
            wl_ip = domain.strip("[ ").rstrip(" ]")
            # check if is an IP address
            try:
                network = ipaddress.ip_network(_format_network_str(str(wl_ip),
                                                                   None))
                # same network
                if ipaddress.ip_address(relay['ip']) in network:
                    match = 1
                    break
            except ValueError:
                # it's not a valid IP - match by rdns
                rdns = relay['rdns'].lower()
                if domain in rdns:
                    match = 1
                    break
        return match

    def check_found_forged(self, address, found_forged):
        if found_forged:
            wlist = self['parsed_whitelist_allow_relays']
            for key in wlist:
                for fuzzy_addr in wlist[key]:
                    if re.search(fuzzy_addr, address):
                        found_forged = 0
                        break
        return found_forged

    def check_uri_host_listed(self, msg, list_name, target=None):
        """Check if the message has URIs that are listed
        in the specified hostname
        """
        if self.get_local(msg, 'enlist_uri_host'):
            return self.get_local(msg, 'enlist_uri_host')
        for uri in msg.uri_list:
            if uri in self['parsed_enlist_uri_host'][list_name]['not_in_list']:
                continue
            for _uri_list_name in self['parsed_enlist_uri_host'][list_name]:
                if uri.endswith(_uri_list_name):
                    return True
        return True

    def check_uri_host_in_whitelist(self, msg, target=None):
        """Shorthand for check_uri_host_listed('WHITE')
        """
        return self.check_uri_host_listed(msg, 'WHITE', None)

    def check_uri_host_in_blacklist(self, msg, target=None):
        """Shorthand for check_uri_host_listed('BLACK')
        """
        return self.check_uri_host_listed(msg, 'BLACK', None)