# База фабрик и мастеров ёлочных игрушек

Каталог для комьюнити «Ёлочные игрушки: мастера и фабрики» (ВК club242169556, ТГ @nytreetoys).
Зачем: не искать каждый раз заново + база для анализа рынка.

- Карточки: JSON в `research/fabriki/` (схема `nytoys-fabrika-card/v1`)
- Исследователь: субагент `nytoys-researcher` — заводит/обновляет карточки, делает срезы рынка
- Аналитические выкладки: `research/reports/YYYY-MM-DD-[тема]-report.md`
- Карточки не связаны с постами напрямую: пост готовит `nytoys-writer`, а в карточке поле `posts_done` показывает, кто уже освещён

Легенда статусов: `проверено` — факты сверены и есть пост; `черновик` — данные с сайта/поиска, до поста уточнить `[уточнить]`.

## Сводная таблица

| Фабрика / мастер | Тип | Город, регион | Техника | Сайт | Соцсети | Статус | Посты |
|---|---|---|---|---|---|---|---|
| [«Ёлочка»](fabriki/yolochka-vysokovsk.json) | фабрика | Высоковск/Клин, МО | стекло, ручная выдувка с 1887 | [yolochka.ru](https://www.yolochka.ru/) | — | проверено | 1 (10.10) |
| [«Рождественское яблоко»](fabriki/rozhdestvenskoe-yabloko-novgorod.json) | мастерская | В. Новгород, Трубичино | выдувка, серебрение, роспись | [christmasapple.com](https://christmasapple.com/) | [VK](https://vk.com/public165747243) | проверено | 1 (10.10) |
| [«Бирюсинка»](fabriki/biryusinka-krasnoyarsk.json) | фабрика | Красноярск | выдувка, НХП (с 1929/1959) | [birusinka24.ru](https://birusinka24.ru/) | [VK](https://vk.com/birusinkatoys), [TG](https://t.me/birusinka_124) | черновик | 0 |
| [«Ариель»](fabriki/ariel-nizhny-novgorod.json) | фабрика | Н. Новгород | выдувка, НХП (1936/1996) | [f-ariel.ru](https://www.f-ariel.ru/) | [VK](https://vk.com/fabrika.ariel), [TG](https://t.me/fabrika_ariel_official) | проверено | 1 (28.10) |
| [«Винтажный шар»](fabriki/vintazhny-shar-novgorod.json) | мастерская | В. Новгород | выдувка, роспись кистью | [vshar.ru](https://vshar.ru/) | [VK](https://vk.com/vintshar) | черновик | 0 |
| [Елена Соколкова](fabriki/elena-sokolkova-rostov.json) | мастер | Ростов-на-Дону | роспись (стекло, «возд. фарфор») | [elenasokolkova.ru](https://elenasokolkova.ru/) | [TG](https://t.me/elenasokolkova) | черновик | 0 |
| [«АРТ ШАРм»](fabriki/art-sharm-moskva.json) | студия | Москва | роспись, брендирование | [artsharm.ru](https://artsharm.ru/) | [TG](https://t.me/artsharm_ng) | черновик | 0 |
| [«Иней»](fabriki/iney-danilovo.json) | фабрика-музей | д. Данилово, МО | выдувка, ≤500 шаров на рисунок | [iney-shop.ru](https://iney-shop.ru/) | [уточнить] | черновик | 0 |
| [«Коломеев»](fabriki/kolomeev-bryansk.json) | фабрика | Брянск, Новозыбков; Калуга | выдувка, металлизация, роспись | [kolomeev.ru](https://kolomeev.ru/) | [VK](https://vk.com/kolomeev_ru), [TG](https://t.me/kolomeev), [Дзен](https://dzen.ru/kolomeev), [ОК](https://ok.ru/group/70000001228540) | проверено | 1 (28.10) |
| [«Ленигрушка»](fabriki/lenigrushka-spb.json) | фабрика | Санкт-Петербург | стекло, керамика (с 2019) | [lenigrushka.ru](https://lenigrushka.ru/) | [VK](https://vk.com/public189324949), [TG](https://t.me/lenigrushka) | проверено | 1 (28.10) |
| [«Тамбовская игрушка»](fabriki/tambovskaya-igrushka-tambov.json) | мастерская | Тамбов | выдувка по техн. XIX в., волки, неваляшки | [tambovskaya-igrushka.ru](https://tambovskaya-igrushka.ru) | [VK](https://vk.ru/tambovskayaigrushka), [TG](https://t.me/tambovskaya_igrushka) | черновик | 0 |
| [«ЭВИС»](fabriki/evis-ivanischi.json) | фабрика | пос. Иванищи, Владимирская обл. | выдувка, 400+ форм (завод с 1845) | [evis.ru](https://evis.ru/) | [TG](https://t.me/evis_glass) | черновик | 0 |
| [«Гутные промыслы»](fabriki/gutnye-promysly-ivanischi.json) | фабрика | пос. Иванищи, Владимирская обл. | цветное гутное стекло, выдувка шаров | [promysel33.ru](https://promysel33.ru/) | — | черновик | 0 |
| [Максим Орлов «Стеклодувы Омска»](fabriki/stekloduvy-omska-orlov.json) | мастер | Омск | выдувка на горелке, авторские шары | — | [уточнить] | черновик | 0 |
| [«Шар-ёлка»](fabriki/shar-elka-mytischi.json) | мастерская | Мытищи, МО | авторская выдувка (Рудакова, Дворцев) | [shar-elka.ru](https://www.shar-elka.ru/) | [VK](https://vk.com/shar.elka), [TG](https://t.me/sharelkashop) | черновик | 0 |
| [«Стеклянная Сказка»](fabriki/steklo-skazka-magnitogorsk.json) | мастерская | Магнитогорск | худ. стекло, Ё-игрушка, МК | [steklo-skazka.ru](https://steklo-skazka.ru/) | [VK](https://vk.com/steklyannay_skazka), [TG](https://t.me/Steklo_skazka) | черновик | 0 |
| [SHARNAELKY](fabriki/sharnaelky-novosibirsk.json) | студия | Новосибирск | роспись шаров, корп. наборы | [sharnaelky.ru](http://sharnaelky.ru/) | [TG](https://t.me/sharnaelky) | черновик | 0 |
| [Мастерская Свияжска](fabriki/sviazhsk-stekloduvnaya.json) | мастерская | о. Свияжск, Татарстан | выдувка при зрителях, музейная | — | [уточнить] | черновик | 0 |
| [«Рождество»](fabriki/rozhdestvo-kresttsy.json) | фабрика | Крестцы, Новгородская обл. | выдувка (300 шаров/день), формовые, 2 техники росписи | [рождествоигрушки.рф](https://рождествоигрушки.рф/) | [уточнить] | черновик | 0 |
| [Мастерская Минаевой](fabriki/minaevdesign-krasnodar.json) | мастерская | Краснодар | стекло, семейная роспись, музей игрушки | [minaeva-design.ru](http://minaeva-design.ru/) [уточнить: сайт нестабилен] | [VK](https://vk.com/minaevdesign) | черновик | 0 |
| [Елена Георгиева](fabriki/georgieva-nahodka.json) | мастер | Находка, Приморье | ватные игрушки, фьюзинг, керамика | — | [уточнить] | черновик | 0 |
| [Archaic Glass](fabriki/archaic-glass-perm.json) | мастер | Пермь | лэмпворк, витраж, ёлочные игрушки по заказу | — | [VK](https://vk.com/archaicglass) | черновик | 0 |
| [Витражная мастерская Х. Цой](fabriki/tsoi-samara.json) | студия | Самара | витраж Тиффани, новогодний декор | — | [VK](https://vk.com/handle.space), [TG](https://t.me/khristina) | черновик | 0 |

Обновлено: 2026-10-28 (23 карточки; +3 поста)