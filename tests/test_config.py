from wsapp_gui.config import AppConfig


def test_appconfig_defaults_and_set_get(tmp_path):
    cfg_path = tmp_path / 'cfg.json'
    appcfg = AppConfig(str(cfg_path))

    # Defaults populated
    assert appcfg.get('theme') == 'light'
    assert isinstance(appcfg.get('notifications'), dict)

    # Set dotted keys and persist
    appcfg.set('theme', 'dark')
    appcfg.set('alerts.account123', False)
    assert appcfg.get('theme') == 'dark'
    assert appcfg.get('alerts.account123') is False

    # Reload from disk
    appcfg2 = AppConfig(str(cfg_path))
    assert appcfg2.get('theme') == 'dark'
    assert appcfg2.get('alerts.account123') is False


def test_window_geometry_parse_and_save(tmp_path):
    cfg_path = tmp_path / 'cfg.json'
    appcfg = AppConfig(str(cfg_path))

    appcfg.save_window_geometry('1024x768+100+50')
    assert appcfg.get('window.width') == 1024
    assert appcfg.get('window.height') == 768
    assert appcfg.get('window.x') == 100
    assert appcfg.get('window.y') == 50

    # Geometry string output contains width and height
    geom = appcfg.get_window_geometry()
    assert '1024x768' in geom


def test_persist_telegram_and_chart_prefs(tmp_path):
    cfg_path = tmp_path / 'cfg.json'
    appcfg = AppConfig(str(cfg_path))

    # Persist Telegram chat id and bot toggle under a custom namespace
    appcfg.set('integrations.telegram.chat_id', '12345')
    appcfg.set('integrations.telegram.enabled', True)
    # Persist chart UI options
    appcfg.set('ui.charts.show_grid', True)
    appcfg.set('ui.charts.show_sma', False)
    appcfg.set('ui.charts.sma_window', 14)

    # Verify retrieval
    assert appcfg.get('integrations.telegram.chat_id') == '12345'
    assert appcfg.get('integrations.telegram.enabled') is True
    assert appcfg.get('ui.charts.show_grid') is True
    assert appcfg.get('ui.charts.show_sma') is False
    assert appcfg.get('ui.charts.sma_window') == 14

    # Reload and verify persistence
    appcfg2 = AppConfig(str(cfg_path))
    assert appcfg2.get('integrations.telegram.chat_id') == '12345'
    assert appcfg2.get('integrations.telegram.enabled') is True
    assert appcfg2.get('ui.charts.show_grid') is True
    assert appcfg2.get('ui.charts.show_sma') is False
    assert appcfg2.get('ui.charts.sma_window') == 14


def test_default_merge_is_non_destructive(tmp_path):
    cfg_path = tmp_path / 'cfg.json'
    # Pre-write a partial config with custom nested values
    cfg_path.write_text('{"integrations": {"telegram": {"enabled": true, "tech_format": "emoji-rich"}}, "notifications": {"info": true}}', encoding='utf-8')

    appcfg = AppConfig(str(cfg_path))
    # Ensure defaults added but existing preserved
    assert appcfg.get('integrations.telegram.enabled') is True
    assert appcfg.get('integrations.telegram.tech_format') == 'emoji-rich'  # preserved
    # Defaults present for missing keys
    assert appcfg.get('integrations.telegram.include_technical') is True
    assert isinstance(appcfg.get('notifications'), dict)
    # Existing notifications.info preserved
    assert appcfg.get('notifications.info') is True
