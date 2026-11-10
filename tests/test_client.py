# -*- coding: utf-8 -*-

"""
Tests of proxy selection and browser-like headers in burst/client.py; run with: python -m pytest tests
"""

import os
import sys
import types

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(1, os.path.join(ROOT, 'resources', 'site-packages'))

# Kodi modules, with Elementum internal proxy and Burst's own proxy both enabled
SETTINGS = {'use_elementum_proxy': True, 'proxy_enabled': True, 'proxy_use_type': 2, 'cookie_sync_enabled': False}


class _Addon(object):
    def __init__(self, id=None):
        pass

    def getAddonInfo(self, key):
        return ROOT if key == 'path' else os.path.join(ROOT, 'tests', '__pycache__', 'profile')

    def getSetting(self, key):
        return 'true' if key == 'internal_proxy_enabled' else ''


def _get_setting(key, converter=str, choices=None):
    return SETTINGS.get(key, converter())


for name in ('xbmc', 'xbmcaddon', 'xbmcvfs', 'xbmcgui', 'elementum', 'elementum.provider'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules['xbmcaddon'].Addon = _Addon
sys.modules['xbmcvfs'].translatePath = lambda path: path
sys.modules['xbmc'].translatePath = lambda path: path
sys.modules['elementum.provider'].log = types.SimpleNamespace(debug=lambda *a: None, info=lambda *a: None, error=lambda *a: None, warning=lambda *a: None)
sys.modules['elementum.provider'].get_setting = _get_setting
sys.modules['elementum.provider'].set_setting = lambda *a: None
sys.modules['elementum.provider'].append_headers = lambda uri, headers: uri

from burst.client import Client  # noqa: E402


def _headers(client, url, **kwargs):
    sent = {}

    def send(prepped, **kw):
        sent.update(prepped.headers)
        raise RuntimeError('not sending')

    client.session.send = send
    client._read_cookies = lambda url='': None
    client.open(url, **kwargs)
    return sent


def test_internal_proxy_wins_over_burst_proxy():
    client = Client(info={'proxy_url': '', 'internal_proxy_url': 'http://10.0.0.1:65222'})
    assert client.session.proxies == {'http': 'http://10.0.0.1:65222', 'https': 'http://10.0.0.1:65222'}


def test_empty_internal_proxy_url_keeps_default():
    client = Client(info={'proxy_url': '', 'internal_proxy_url': ''})
    assert client.session.proxies['https'] == 'http://127.0.0.1:65222'


def test_navigation_headers():
    headers = _headers(Client(), 'https://site.org/search?q=1')
    assert headers['Sec-Fetch-Mode'] == 'navigate'
    assert 'Origin' not in headers
    assert 'Content-Language' not in headers
    assert 'Cache-Control' not in headers
    assert headers['Priority'] == 'u=0, i'


def test_firefox_accept():
    client = Client()
    client.user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:157.0) Gecko/20100101 Firefox/157.0'
    assert _headers(client, 'https://site.org/')['Accept'] == 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'


def test_post_origin_has_no_path():
    headers = _headers(Client(), 'https://site.org/login.php', post_data={'a': 'b'})
    assert headers['Origin'] == 'https://site.org'


def test_xhr_headers():
    headers = _headers(Client(), 'https://site.org/details', headers={'X-Requested-With': 'XMLHttpRequest'})
    assert headers['Sec-Fetch-Mode'] == 'cors'
    assert 'Sec-Fetch-User' not in headers
    assert 'Upgrade-Insecure-Requests' not in headers


def test_api_headers():
    headers = _headers(Client(is_api=True), 'https://api.site.org/v1')
    assert 'Sec-Fetch-Mode' not in headers
    assert 'Referer' not in headers


def test_vietmediaf_provider_definition_and_api_extraction():
    import json
    from burst.providers.definitions import definitions
    from burst.burst import extract_from_api

    assert 'vietmediaf' in definitions
    vmf = definitions['vietmediaf']
    assert vmf['enabled'] is True
    assert vmf['private'] is True
    assert vmf['is_api'] is True
    assert vmf['login_apikey'] is True
    assert vmf['base_url'] == 'https://tracker.vietmediaf.store/api/torrents/filter'
    assert definitions['seedpool']['login_apikey'] is True

    client = Client(is_api=True)
    client.passkey = 'test_api_key_123'
    client.content = json.dumps({
        'data': [
            {
                'id': '101',
                'attributes': {
                    'name': 'Example.Movie.2026.ViE.DUB.2160p.WEB-DL.DV.HDR.H.265-VMF',
                    'size': 10737418240,
                    'seeders': 12,
                    'leechers': 2,
                    'freeleech': '100%',
                    'download_link': 'https://tracker.vietmediaf.store/torrent/download/101.rsskey123'
                }
            },
            {
                'id': '102',
                'attributes': {
                    'name': 'Example.Movie.2026.ViE.1080p.WEB-DL.H.264-VMF',
                    'size': 4294967296,
                    'seeders': 8,
                    'leechers': 0,
                    'freeleech': '0%',
                    'download_link': 'https://tracker.vietmediaf.store/torrent/download/102.rsskey123'
                }
            }
        ]
    })
    items = list(extract_from_api('vietmediaf', client))
    assert len(items) == 2
    assert items[0][0] == 'Example.Movie.2026.ViE.DUB.2160p.WEB-DL.DV.HDR.H.265-VMF'
    assert items[0][2] == 'https://tracker.vietmediaf.store/torrent/download/101.rsskey123'
    assert items[0][3] == '10.0 GB'
    assert items[0][4] == 12
    assert items[0][5] == 2
    assert items[0][6] == 'ViE DUB · FL'
    assert items[1][6] == 'ViE'

    unit3d_providers = [k for k, v in definitions.items() if v.get('login_apikey')]
    assert len(unit3d_providers) == 45

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    with open(os.path.join(repo_root, 'resources', 'settings.xml'), 'r', encoding='utf-8') as f:
        settings_xml = f.read()

    for pid in unit3d_providers:
        pdef = definitions[pid]
        assert pdef['enabled'] is True
        assert pdef['private'] is True
        assert pdef['is_api'] is True
        assert pdef['base_url'].endswith('/api/torrents/filter')
        assert 'Bearer ' in pdef['headers']
        assert os.path.isfile(os.path.join(repo_root, 'burst', 'providers', 'icons', '%s.png' % pid))
        assert 'id="%s_passkey" label="32182"' % pid in settings_xml
        assert 'id="%s_username"' % pid not in settings_xml

    aither_items = list(extract_from_api('aither', client))
    assert len(aither_items) == 2
    assert aither_items[0][6] == 'FL'
    assert aither_items[1][6] == ''



if __name__ == '__main__':
    for name, test in list(globals().items()):
        if name.startswith('test_'):
            test()
            print('ok', name)
