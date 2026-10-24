/* Сообщения облака лабораторий (electron REQ-086, REQ-087, DEC-058, DEC-060): вход и выход, каталог, подключение из облака, публикация, приглашения,
   проверка обновлений (cloud_http.py, cloud_session.py, cloud_client.py, api/routes_cloud.py). Отказ самого облака приходит вложенным:
   «the cloud refused the request: …» — вложенная часть переводится по известным сообщениям службы (cloud/). Загружается перед i18n-gaps.js. */
'use strict';
(() => {
  const WHERE = {'the cloud': 'Облако', 'the sign-in service': 'Служба входа'};
  const where = (s) => WHERE[s] || s;
  // what the service itself answers (cloud/titanium_cloud); anything else stays the service's text
  const SERVICE = [
    [/^HTTP (\d+)$/i, (m) => `ответ HTTP ${m[1]}`],
    [/^sign-in is not configured on this service$/i, 'вход на этой службе не настроен'],
    [/^the session expired: sign in again$/i, 'сеанс истёк: войдите снова'],
    [/^use a Bearer token$/i, 'нужен токен входа'],
    [/^the token (is not a JWT|names no account|was not signed by a known key)$/i, 'токен входа не принят: войдите снова'],
    [/^the token is not valid: .*$/i, 'токен входа недействителен: войдите снова'],
    [/^the token's algorithm .* is not accepted$/i, 'токен входа подписан неподдерживаемым способом'],
    [/^there is no such (laboratory|release|publication|invitation|member)$/i, (m) => `такой ${{laboratory: 'лаборатории', release: 'выпуска', publication: 'публикации', invitation: 'приглашения', member: 'участника'}[m[1]]} нет`],
    [/^(this|the) laboratory is private$/i, 'лаборатория закрытая: нужно приглашение'],
    [/^only the owner of the laboratory may do this$/i, 'это может сделать только владелец лаборатории'],
    [/^a laboratory needs a name and an author$/i, 'лаборатории нужны название и автор'],
    [/^a laboratory with this origin id is in the catalogue already$/i, 'лаборатория с таким идентификатором уже есть в каталоге'],
    [/^(.+) is longer than (\d+) characters$/i, (m) => `${m[1]} длиннее ${m[2]} символов`],
    [/^(.+) is not an acceptable link: .*$/i, (m) => `${m[1]}: ссылка не принята`],
    [/^this idempotency key was used for another laboratory$/i, 'ключ публикации уже использован для другой лаборатории'],
    [/^the laboratory's latest release is not the one expected: another release was published$/i, 'последний выпуск лаборатории не тот, что ожидался: опубликован другой выпуск'],
    [/^another release was published since this publication was reserved$/i, 'с момента резервирования опубликован другой выпуск'],
    [/^the publication is finalized(?: with other content)?: a release never changes$/i, 'публикация уже завершена: выпуск не меняется'],
    [/^the upload expired: reserve a new publication$/i, 'время передачи вышло: начните публикацию заново'],
    [/^a chunk cannot be empty$/i, 'пустая часть файла'],
    [/^the chunk is missing$/i, 'части файла нет'],
    [/^chunks not uploaded yet: .*$/i, 'переданы не все части файла'],
    [/^the chunks hold (\d+) bytes, the publication declared (\d+)$/i, (m) => `передано ${m[1]} байт, объявлено ${m[2]}`],
    [/^the uploaded bytes do not match the declared file hash$/i, 'переданный файл не совпадает с объявленным хешем'],
    [/^the release has chunks 0 to (\d+)$/i, (m) => `у выпуска части от 0 до ${m[1]}`],
    [/^the release is not acceptable: (.*)$/i, (m) => `выпуск не принят: ${m[1]}`],
    [/^the release id is not the one reserved for this publication$/i, 'идентификатор выпуска не тот, что зарезервирован'],
    [/^the release number must be (\d+), the one reserved$/i, (m) => `номер выпуска должен быть ${m[1]} — зарезервированный`],
    [/^the release is not of this laboratory: its origin laboratory id differs$/i, 'выпуск не этой лаборатории: идентификатор лаборатории другой'],
    [/^the release names another author than the laboratory's$/i, 'в выпуске другой автор, чем у лаборатории'],
    [/^the release names the laboratory differently from the catalogue$/i, 'в выпуске название лаборатории не такое, как в каталоге'],
    [/^the invitation (expired|was revoked|was used by someone else)$/i, (m) => ({expired: 'приглашение истекло', 'was revoked': 'приглашение отозвано',
      'was used by someone else': 'приглашение уже использовано другим'})[m[1]]],
    [/^this withdrawal is declared already$/i, 'этот отзыв уже объявлен'],
  ];
  const service = (text) => {
    for (const [re, to] of SERVICE) {
      const m = text.match(re);
      if (m) return typeof to === 'function' ? to(m) : to;
    }
    return text;
  };
  I18N.add([
    // cloud_http.py
    [/^the cloud of laboratories is switched off in the network settings of this workshop$/i, 'Облако лабораторий выключено в настройках сети этой мастерской'],
    [/^(the cloud|the sign-in service) could not be reached: (.*)$/i, (m) => `${where(m[1])} недоступно: ${m[2]}. Проверьте подключение к интернету`],
    [/^the cloud does not accept this sign-in any more: sign in again$/i, 'Облако больше не принимает этот вход: войдите снова'],
    [/^(the cloud|the sign-in service) refused the request: (.*)$/i, (m) => `${where(m[1])} отклонило запрос: ${service(m[2])}`],
    // cloud_session.py
    [/^the address of the cloud is text$/i, 'Адрес облака — текст'],
    [/^the address of the cloud is an https address \(http only on this computer\)$/i, 'Адрес облака — адрес https (http только на этом компьютере)'],
    [/^the cloud does not offer sign-in: it is not configured for it$/i, 'Облако не предлагает вход: вход на нём не настроен'],
    [/^this sign-in is not expected: start it again from the application$/i, 'Приложение не ждало этот вход: начните вход заново из приложения'],
    [/^the sign-in code is missing$/i, 'Кода входа нет'],
    [/^the sign-in service named no account for this sign-in: sign in again$/i, 'Служба входа не назвала аккаунт для этого входа: войдите снова'],
    [/^the sign-in service names another issuer than the cloud does$/i, 'Служба входа называет не того издателя, что облако: вход невозможен'],
    [/^the discovery document of the sign-in service is not as expected$/i, 'Описание службы входа не такое, как ожидалось: вход невозможен'],
    [/^the sign-in was cancelled at the sign-in service$/i, 'Вход отменён в службе входа'],
    [/^the sign-in service answered with an error: (.*)$/i, (m) => `Служба входа ответила ошибкой: ${m[1]}`],
    [/^the sign-in service refused the code: (.*)$/i, (m) => `Служба входа не приняла код входа: ${m[1]}`],
    [/^the sign-in service did not renew the sign-in: (.*)$/i, (m) => `Служба входа не продлила вход: ${m[1]}`],
    [/^the sign-in service gave no refresh token: sign in again$/i, 'Служба входа не выдала токен продления: войдите снова'],
    [/^sign in to the cloud first$/i, 'Сначала войдите в облако'],
    [/^the cloud sign-in expired: sign in again$/i, 'Вход в облако истёк: войдите снова'],
    [/^the sign-in service gave no token: sign in again$/i, 'Служба входа не выдала токен: войдите снова'],
    // cloud_client.py
    [/^the operation was cancelled: nothing changed$/i, 'Операция отменена: ничего не изменилось'],
    [/^the operation failed: (.*)$/i, (m) => `Операция не удалась: ${m[1]}`],
    [/^no such cloud operation$/i, 'Такой операции с облаком нет'],
    [/^no such (laboratory|release) in the cloud$/i, (m) => (m[1] === 'release' ? 'Такого выпуска в облаке нет' : 'Такой лаборатории в облаке нет')],
    [/^no such publication$/i, 'Такой публикации нет'],
    [/^the cloud sent a chunk larger than it declared$/i, 'Облако прислало часть файла больше объявленной'],
    [/^the downloaded release does not match the hash the cloud declares: nothing was connected$/i, 'Загруженный выпуск не совпадает с хешем, объявленным облаком: ничего не подключено'],
    [/^a laboratory with this workshop's identity exists in the cloud under another account$/i, 'Лаборатория с идентификатором этой мастерской уже есть в облаке под другой учётной записью'],
    [/^enter the laboratory's public name and the author before publishing$/i, 'Перед публикацией укажите публичное название лаборатории и автора'],
    [/^the visibility of the laboratory is public or private$/i, 'Видимость лаборатории — открытая или закрытая'],
    [/^choose usage terms from the approved list$/i, 'Выберите условия использования из утверждённого списка'],
    [/^a publication is still pending: continue it or give it up first$/i, 'Публикация ещё не завершена: сначала продолжите её или откажитесь'],
    [/^there is no pending publication to continue$/i, 'Незавершённой публикации нет: продолжать нечего'],
    [/^there is no pending publication to give up$/i, 'Незавершённой публикации нет: отказываться не от чего'],
    [/^another publication is running: wait until it ends$/i, 'Идёт другая публикация: дождитесь её конца'],
    [/^the cloud no longer takes this publication: it expired or failed there; publish again$/i, 'Облако больше не принимает эту публикацию: она истекла или не удалась там; опубликуйте заново'],
    [/^the exported file of this publication is gone from lab_exports: publish again$/i, 'Файл выпуска этой публикации пропал из lab_exports: опубликуйте заново'],
    [/^given up by the operator$/i, 'отменена оператором'],
    [/^this workshop has no laboratory in the cloud yet: publish a release first$/i, 'У этой мастерской ещё нет лаборатории в облаке: сначала опубликуйте выпуск'],
    [/^paste the invitation link as it was given$/i, 'Вставьте ссылку приглашения так, как она была передана'],
    [/^no such connected laboratory$/i, 'Такой подключённой лаборатории нет'],
    [/^this laboratory was connected from a file: a newer release is connected from a file too$/i, 'Эта лаборатория подключена из файла: более новый выпуск тоже подключается из файла'],
    [/^the check for updates of a laboratory is manual or auto$/i, 'Проверка обновлений лаборатории — по кнопке или автоматически'],
    [/^reconnect the laboratory first: a disconnected one is not checked$/i, 'Сначала подключите лабораторию снова: отключённая не проверяется'],
    // api/routes_cloud.py
    [/^the lifetime of an invitation is a number of seconds, at least 60$/i, 'Срок приглашения — число секунд, не меньше 60'],
    [/^the laboratory to check is named by its number$/i, 'Лаборатория для проверки указывается номером'],
  ]);
})();
