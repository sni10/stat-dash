"""The 22 cities of lun.ua/stat with LUN's cityId (checked 19.11.2026). Only Odesa is enabled; enable more in the
admin or with `UPDATE city SET enabled = true WHERE slug = '...'` — no code change needed."""
from django.db import migrations

CITIES = [
    (1, 'kyiv', 'Київ'),
    (103, 'vinnytsia', 'Вінниця'),
    (104, 'lutsk', 'Луцьк'),
    (105, 'dnipro', 'Дніпро'),
    (107, 'zhytomyr', 'Житомир'),
    (108, 'uzhhorod', 'Ужгород'),
    (109, 'zaporizhzhia', 'Запоріжжя'),
    (110, 'ivano-frankivsk', 'Івано-Франківськ'),
    (111, 'kropyvnytskyi', 'Кропивницький'),
    (113, 'lviv', 'Львів'),
    (114, 'mykolaiv', 'Миколаїв'),
    (115, 'odesa', 'Одеса'),
    (116, 'poltava', 'Полтава'),
    (117, 'rivne', 'Рівне'),
    (118, 'sumy', 'Суми'),
    (119, 'ternopil', 'Тернопіль'),
    (120, 'kharkiv', 'Харків'),
    (121, 'kherson', 'Херсон'),
    (122, 'khmelnytskyi', 'Хмельницький'),
    (123, 'cherkasy', 'Черкаси'),
    (124, 'chernivtsi', 'Чернівці'),
    (125, 'chernihiv', 'Чернігів'),
]
ENABLED = {'odesa'}


def seed(apps, schema_editor):
    City = apps.get_model('collector', 'City')
    for city_id, slug, name in CITIES:
        City.objects.update_or_create(id=city_id, defaults={'slug': slug, 'name': name, 'enabled': slug in ENABLED})


class Migration(migrations.Migration):
    dependencies = [('collector', '0001_initial')]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
