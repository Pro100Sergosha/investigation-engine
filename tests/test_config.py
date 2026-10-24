from engine import config


def test_embed_model_default():
    assert config.EMBED_MODEL


def test_aws_settings_are_strings_without_env():
    # Tests run without AWS resources: missing settings are empty, never None.
    for value in (config.DB_HOST, config.DB_NAME, config.DB_USER, config.BUCKET):
        assert isinstance(value, str)
