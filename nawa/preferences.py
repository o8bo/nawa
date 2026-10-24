"""Language and display currency preferences, independent of the ledger data."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import os
from pathlib import Path
import tempfile
from .paths import config_directory


@dataclass(frozen=True)
class Preferences:
    language: str = 'ar'
    currency: str = 'SAR'
    usd_rate: Decimal = Decimal('3.75')


def settings_path():
    override = os.environ.get('NAWA_SETTINGS_PATH')
    if override:
        return Path(override)
    # Alternate databases get their own preferences, including test databases.
    if os.environ.get('NAWA_DB_PATH'):
        return Path(os.environ['NAWA_DB_PATH']).with_suffix('.preferences.json')
    return config_directory() / 'preferences.json'


def validated(language, currency, rate):
    if language not in ('ar', 'en') or currency not in ('SAR', 'USD'):
        raise ValueError('إعدادات اللغة أو العملة غير صالحة.')
    try:
        from .finance_store import DIGITS
        value = Decimal(str(rate).translate(DIGITS).replace('٫', '.'))
        if not value.is_finite() or not Decimal('0.0001') <= value <= Decimal('1000000'):
            raise ValueError
    except (InvalidOperation, ValueError):
        raise ValueError('أدخل سعر تحويل موجبًا بين 0.0001 و1000000.') from None
    return Preferences(language, currency, value)


def read_settings():
    try:
        data = json.loads(settings_path().read_text(encoding='utf-8'))
        return validated(data['language'], data['currency'], data['usd_rate'])
    except (OSError, ValueError, TypeError, KeyError):
        return Preferences()


settings = read_settings()


def set_settings(language, currency, rate):
    global settings
    candidate = validated(language, currency, rate)
    path = settings_path(); path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
            name = handle.name
            json.dump(dict(language=candidate.language, currency=candidate.currency, usd_rate=str(candidate.usd_rate)), handle)
            handle.write('\n')
        os.replace(name, path)
    finally:
        if name and os.path.exists(name): os.unlink(name)
    settings = candidate


def display_minor(minor):
    return Decimal(minor) / (settings.usd_rate if settings.currency == 'USD' else Decimal(1))


def formatted(minor):
    value = (display_minor(minor) / 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    return f'{value:,.2f}'


def input_amount(value, original=None):
    """Convert entered display currency to SAR; retain exact unchanged records."""
    from .finance_store import money, MAX_MINOR
    if original is not None and value == formatted(original).replace(',', ''):
        return str(Decimal(original) / 100)
    minor = money(value, allow_zero=True)
    if settings.currency == 'USD':
        minor = int((Decimal(minor) * settings.usd_rate).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if minor > MAX_MINOR:
        raise ValueError('أدخل مبلغًا موجبًا ضمن النطاق المدعوم.')
    return str(Decimal(minor) / 100)


def currency_symbol():
    return '$' if settings.currency == 'USD' else ('ر.س' if settings.language == 'ar' else 'SAR')


def currency_name():
    from .i18n import tr
    return tr('دولار أمريكي' if settings.currency == 'USD' else 'ريال سعودي')
