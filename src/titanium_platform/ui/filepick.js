/* Выбор файла в стиле приложения. Нативное <input type=file> рисует браузер: надпись «Choose File / no file selected»
   по-английски и кнопка не по центру поля. Здесь настоящий input остаётся (клавиатура, доступность, форма), но
   визуально скрыт, а видимая часть — кнопка «Выбрать файл» и имя выбранного файла по-русски.
   App.filePick(input, label) возвращает узел-обёртку; input по-прежнему используется как обычно (input.files). */
'use strict';
Object.assign(App, (() => {
  const {h} = App;
  const size = (n) => (n < 1024 * 1024 ? Math.max(1, Math.round(n / 1024)) + ' КБ' : (n / 1024 / 1024).toFixed(1).replace('.', ',') + ' МБ');

  function filePick(input, buttonLabel = 'Выбрать файл') {
    input.classList.add('file-native');
    const name = h('span', {class: 'file-name'}, 'Файл не выбран');
    const box = h('span', {class: 'file-pick'}, h('span', {class: 'btn btn-small file-button', 'aria-hidden': 'true'}, buttonLabel), name);
    const sync = () => {
      const f = input.files && input.files[0];
      name.textContent = f ? `${f.name} · ${size(f.size)}` : 'Файл не выбран';
      box.classList.toggle('has-file', !!f);
    };
    input.addEventListener('change', sync);
    // a caller may set input.files programmatically (tests, drag and drop): keep the name in step
    box.refresh = sync;
    return h('span', {class: 'file-field'}, input, box);
  }
  return {filePick};
})());
