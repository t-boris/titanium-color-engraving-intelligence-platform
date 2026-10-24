/* Сообщения о локальной сети и внешних службах (electron REQ-080, REQ-082): сопряжение планшета, устройства, переключатели сети и отказы
   защиты локального API. Загружается перед i18n-gaps.js. */
'use strict';
(() => {
  I18N.add([
    [/^the port of the local network server must be a number between 1024 and 65535$/i, 'Порт сервера локальной сети — число от 1024 до 65535'],
    [/^the name of this workshop on the network is one to 64 characters$/i, 'Имя мастерской в сети — от 1 до 64 знаков'],
    [/^the name of the device is one to 64 characters$/i, 'Имя планшета — от 1 до 64 знаков'],
    [/^there is no pairing code now: ask for a new one on the network screen of the workshop$/i,
      'Кода сейчас нет: попросите новый на экране «Сеть» мастерской'],
    [/^the pairing code was entered wrongly too many times and is cancelled: ask for a new one on the network screen of the workshop$/i,
      'Код введён неверно слишком много раз и отменён: попросите новый на экране «Сеть» мастерской'],
    [/^the pairing code is wrong: check the six digits on the network screen of the workshop$/i, 'Код неверный: сверьте шесть цифр на экране «Сеть» мастерской'],
    [/^there is no device (\d+)$/i, (m) => `Планшета № ${m[1]} нет`],
    [/^the network settings are switches: each value is true or false$/i, 'Настройки сети — переключатели: каждое значение включено или выключено'],
    [/^Google Fonts are switched off in the network settings of this workshop$/i, 'Google Fonts выключены в настройках сети этой мастерской'],
    // the guard of the local API (api/security.py)
    [/^this address does not name this computer$/i, 'Этот адрес не указывает на этот компьютер'],
    [/^a request from another site cannot change this workshop$/i, 'Запрос с другого сайта не может изменить эту мастерскую'],
    [/^the request is larger than (\d+) MB$/i, (m) => `Запрос больше ${m[1]} МБ`],
    [/^this session address is not valid$/i, 'Этот адрес сеанса недействителен'],
    [/^open the workshop from the application$/i, 'Откройте мастерскую из приложения'],
    [/^the desktop session is not opened from the network$/i, 'Сеанс настольного приложения не открывается из сети'],
    [/^pair this tablet with the workshop first: open \/pair on it$/i, 'Сначала подключите этот планшет к мастерской: откройте на нём страницу /pair'],
    [/^this is done on the workshop's own computer, not from a device on the network$/i,
      'Это делается на компьютере мастерской, а не с устройства в сети'],
  ]);
})();
