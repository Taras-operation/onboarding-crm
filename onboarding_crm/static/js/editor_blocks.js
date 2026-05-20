let blockCounter = 0;

const richEditors = new Map();

function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value || '';
  return div.innerHTML;
}

function initRichEditor(editorEl, hiddenInput, initialValue = '') {
  if (!editorEl || !hiddenInput) return;

  if (typeof Quill === 'undefined') {
    hiddenInput.value = initialValue || '';
    return;
  }

  const quill = new Quill(editorEl, {
    theme: 'snow',
    placeholder: editorEl.getAttribute('data-placeholder') || 'Опис...',
    modules: {
      toolbar: [
        [{ header: [1, 2, 3, false] }],
        ['bold', 'italic', 'underline'],
        [{ list: 'ordered' }, { list: 'bullet' }],
        ['link'],
        ['clean']
      ]
    }
  });

  quill.clipboard.dangerouslyPasteHTML(initialValue || '');
  hiddenInput.value = quill.root.innerHTML;
  editorEl.__quill = quill;
  richEditors.set(hiddenInput.name, quill);

  quill.on('text-change', () => {
    hiddenInput.value = quill.root.innerHTML;

    if (typeof window.autosaveTemplate === 'function') {
      clearTimeout(window.__richAutosaveTimer);
      window.__richAutosaveTimer = setTimeout(() => {
        try { window.autosaveTemplate(); } catch (_) {}
      }, 800);
    }
  });
}

function syncRichEditors() {
  richEditors.forEach((quill, inputName) => {
    const input = document.querySelector(`[name="${inputName}"]`);
    if (input) input.value = quill.root.innerHTML;
  });
}

function rebuildRichEditorsMap() {
  richEditors.clear();

  document.querySelectorAll('.rich-editor-wrapper').forEach(wrapper => {
    const hiddenInput = wrapper.querySelector('.rich-hidden');
    const editorEl = wrapper.querySelector('.rich-editor');
    const quill = editorEl?.__quill;

    if (hiddenInput && quill) {
      richEditors.set(hiddenInput.name, quill);
    }
  });
}

function reinitRichEditorsFromDOM() {
  richEditors.clear();

  document.querySelectorAll('.rich-editor-wrapper').forEach(wrapper => {
    const hiddenInput = wrapper.querySelector('.rich-hidden');
    const oldEditorEl = wrapper.querySelector('.rich-editor');

    if (!hiddenInput || !oldEditorEl) return;

    const existingHtml =
      hiddenInput.value ||
      oldEditorEl.querySelector('.ql-editor')?.innerHTML ||
      oldEditorEl.innerHTML ||
      '';

    // Autosave може відновити "мертвий" Quill DOM без JS-обробників.
    // Тому видаляємо старий toolbar/container і створюємо editor заново.
    wrapper.querySelectorAll('.ql-toolbar').forEach(toolbar => toolbar.remove());

    const freshEditor = document.createElement('div');
    freshEditor.className = 'rich-editor bg-white';
    freshEditor.setAttribute(
      'data-placeholder',
      oldEditorEl.getAttribute('data-placeholder') || 'Опис...'
    );

    oldEditorEl.replaceWith(freshEditor);

    initRichEditor(
      freshEditor,
      hiddenInput,
      existingHtml
    );
  });
}

// ===== Helpers: lock completed blocks (read-only) =====
function lockBlock(blockDiv) {
  blockDiv.classList.add('locked', 'opacity-75');
  blockDiv.querySelectorAll('input, textarea, select, button').forEach(el => {
    if (el.classList.contains('drag-handle')) return;
    el.disabled = true;
  });

  if (!blockDiv.querySelector('.lock-badge')) {
    const badge = document.createElement('div');
    badge.className = 'lock-badge absolute top-2 left-10 text-xs bg-gray-200 text-gray-700 px-2 py-1 rounded';
    badge.innerText = '🔒 Пройдено — редагування заблоковано';
    blockDiv.appendChild(badge);
  }
  blockDiv.querySelectorAll('.rich-hidden').forEach(input => {
    const quill = richEditors.get(input.name);
    if (quill) quill.enable(false);
  });
}

function unlockBlock(blockDiv) {
  blockDiv.classList.remove('locked', 'opacity-75');
  blockDiv.querySelectorAll('input, textarea, select, button').forEach(el => {
    if (el.classList.contains('drag-handle')) return;
    el.disabled = false;
  });
  const badge = blockDiv.querySelector('.lock-badge');
  if (badge) badge.remove();
  blockDiv.querySelectorAll('.rich-hidden').forEach(input => {
    const quill = richEditors.get(input.name);
    if (quill) quill.enable(true);
  });
}

// ===== Helpers: empty checks =====
function isMeaningfulText(value) {
  return (value || '').toString().trim() !== '';
}

function isEmptyStageData(data = {}) {
  const hasTitle = isMeaningfulText(data.title);
  const hasDescription = isMeaningfulText(data.description);
  const hasSubblocks = Array.isArray(data.subblocks) && data.subblocks.some(
    s => isMeaningfulText(s?.title) || isMeaningfulText(s?.description)
  );
  const hasTests = Array.isArray(data?.test?.questions) && data.test.questions.some(q => {
    const hasQuestion = isMeaningfulText(q?.question);
    const hasAnswers = Array.isArray(q?.answers) && q.answers.some(a => isMeaningfulText(a?.value));
    return hasQuestion || hasAnswers;
  });
  const hasOpenQuestions = Array.isArray(data.open_questions) && data.open_questions.some(
    q => isMeaningfulText(q?.question)
  );

  return !(hasTitle || hasDescription || hasSubblocks || hasTests || hasOpenQuestions);
}

// 🔄 Перенумерация блоков
function renumberBlocks() {
  const blocks = document.querySelectorAll('#blocks-container > .block');
  blocks.forEach((blockDiv, i) => {
    const titleEl = blockDiv.querySelector('h3');
    if (titleEl) titleEl.innerText = `Блок №${i + 1}`;

    blockDiv.querySelectorAll('input, textarea, select').forEach(input => {
      if (input.name && input.name.includes('blocks')) {
        input.name = input.name.replace(/blocks\[\d+\]/, `blocks[${i}]`);
      }
    });

    renumberSubblocks(blockDiv, i);
    renumberTests(blockDiv, i);
    renumberOpenQuestions(blockDiv, i);
  });

  blockCounter = blocks.length;
  rebuildRichEditorsMap();
}

// 🔄 Перенумерация сабблоков
function renumberSubblocks(blockDiv, blockIndex) {
  const subblocks = blockDiv.querySelectorAll('.subblock');
  subblocks.forEach((subDiv, i) => {
    subDiv.querySelectorAll('input, textarea').forEach(input => {
      if (input.name && input.name.includes('subblocks')) {
        input.name = input.name.replace(/subblocks\]\[\d+\]/, `subblocks][${i}]`);
      }
    });
  });
}

// 🔄 Перенумерация тестов
function renumberTests(blockDiv, blockIndex) {
  const tests = blockDiv.querySelectorAll('.test');
  tests.forEach((testDiv, i) => {
    testDiv.querySelectorAll('input, textarea').forEach(input => {
      if (input.name && input.name.includes('questions')) {
        input.name = input.name.replace(/questions\]\[\d+\]/, `questions][${i}]`);
      }
    });
    renumberAnswers(testDiv, blockIndex, i);
  });
}

// 🔄 Перенумерация открытых вопросов
function renumberOpenQuestions(blockDiv, blockIndex) {
  const openQs = blockDiv.querySelectorAll('.open-question');
  openQs.forEach((qDiv, i) => {
    qDiv.querySelectorAll('input').forEach(input => {
      if (input.name && input.name.includes('open_questions')) {
        input.name = input.name.replace(/open_questions\]\[\d+\]/, `open_questions][${i}]`);
      }
    });
  });
}

// 🔄 Перенумерация ответов
function renumberAnswers(testDiv, blockIndex, testIndex) {
  const answers = testDiv.querySelectorAll('.answer');
  answers.forEach((aDiv, i) => {
    aDiv.querySelectorAll('input').forEach(input => {
      if (input.name && input.name.includes('answers')) {
        input.name = input.name.replace(/answers\]\[\d+\]/, `answers][${i}]`);
      }
    });
  });
}

// ❌ Удаление блока
function deleteBlock(btn) {
  const blk = btn.closest('.block');
  if (blk && blk.classList.contains('locked')) {
    alert('Цей етап вже пройдений і не може бути видалений.');
    return;
  }
  blk.remove();
  renumberBlocks();
}

// ❌ Удаление сабблока
function deleteSubblock(btn) {
  const blockDiv = btn.closest('.block');
  if (blockDiv && blockDiv.classList.contains('locked')) {
    alert('Цей етап вже пройдений і не може бути змінений.');
    return;
  }
  btn.closest('.subblock').remove();
  renumberSubblocks(blockDiv);
}

// ❌ Удаление теста
function deleteTest(btn) {
  const blockDiv = btn.closest('.block');
  if (blockDiv && blockDiv.classList.contains('locked')) {
    alert('Цей етап вже пройдений і не може бути змінений.');
    return;
  }
  btn.closest('.test').remove();
  renumberTests(blockDiv);
}

// ❌ Удаление ответа
function deleteAnswer(btn) {
  const testDiv = btn.closest('.test');
  const blockDiv = btn.closest('.block');
  if (blockDiv && blockDiv.classList.contains('locked')) {
    alert('Цей етап вже пройдений і не може бути змінений.');
    return;
  }
  btn.closest('.answer').remove();
  renumberAnswers(testDiv);
}

// ❌ Удаление открытого вопроса
function deleteOpenQuestion(btn) {
  const blockDiv = btn.closest('.block');
  if (blockDiv && blockDiv.classList.contains('locked')) {
    alert('Цей етап вже пройдений і не може бути змінений.');
    return;
  }
  btn.closest('.open-question').remove();
  renumberOpenQuestions(blockDiv);
}

// 🔀 Compact reorder mode for large templates
function getBlockTitleForReorder(blockDiv, index) {
  const title = blockDiv.querySelector('[name^="blocks"][name$="[title]"]')?.value?.trim();
  return title || `Блок №${index + 1}`;
}

function ensureReorderModal() {
  if (document.getElementById('reorderBlocksModal')) return;

  const modal = document.createElement('div');
  modal.id = 'reorderBlocksModal';
  modal.className = 'fixed inset-0 z-50 hidden items-center justify-center bg-black bg-opacity-50 p-4';
  modal.innerHTML = `
    <div class="bg-white rounded-lg shadow-xl w-full max-w-3xl max-h-[90vh] flex flex-col">
      <div class="flex items-center justify-between border-b px-5 py-4">
        <div>
          <h2 class="text-xl font-bold">Змінити порядок блоків</h2>
          <p class="text-sm text-gray-500 mt-1">Перетягни блоки у компактному списку або використовуй ↑ ↓</p>
        </div>
        <button type="button" class="text-gray-500 hover:text-gray-800 text-2xl" onclick="closeReorderModal()">×</button>
      </div>

      <div class="p-5 overflow-y-auto">
        <div id="reorderBlocksList" class="space-y-2"></div>
      </div>

      <div class="border-t px-5 py-4 flex justify-end gap-2">
        <button type="button" class="px-4 py-2 rounded border bg-white hover:bg-gray-50" onclick="closeReorderModal()">Скасувати</button>
        <button type="button" class="px-4 py-2 rounded bg-blue-600 text-white hover:bg-blue-700" onclick="applyReorderBlocks()">Зберегти порядок</button>
      </div>
    </div>
  `;

  document.body.appendChild(modal);
}

function openReorderModal() {
  syncRichEditors();
  ensureReorderModal();
  renderReorderList();

  const modal = document.getElementById('reorderBlocksModal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

function closeReorderModal() {
  const modal = document.getElementById('reorderBlocksModal');
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

function renderReorderList() {
  const list = document.getElementById('reorderBlocksList');
  if (!list) return;

  const blocks = Array.from(document.querySelectorAll('#blocks-container > .block'));

  if (!blocks.length) {
    list.innerHTML = '<div class="text-gray-500 text-sm border rounded p-4 bg-gray-50">Поки що немає блоків для сортування.</div>';
    return;
  }

  list.innerHTML = blocks.map((block, index) => {
    const title = escapeHtml(getBlockTitleForReorder(block, index));
    const locked = block.classList.contains('locked');
    const subCount = block.querySelectorAll('.subblock').length;
    const testCount = block.querySelectorAll('.test').length;
    const openCount = block.querySelectorAll('.open-question').length;

    return `
      <div class="reorder-item border rounded-lg bg-gray-50 p-3 flex items-center gap-3 ${locked ? 'opacity-60' : ''}"
           data-block-id="${block.dataset.reorderId}"
           data-locked="${locked ? '1' : '0'}">
        <div class="reorder-handle cursor-move text-gray-400 text-xl" title="Перетягнути">⋮⋮</div>
        <div class="w-10 h-10 rounded bg-blue-100 text-blue-700 flex items-center justify-center font-bold shrink-0">${index + 1}</div>
        <div class="min-w-0 flex-1">
          <div class="font-semibold truncate">${title}</div>
          <div class="text-xs text-gray-500 mt-1">
            Сабблоків: ${subCount} · Тестів: ${testCount} · Відкритих питань: ${openCount}${locked ? ' · 🔒 Locked' : ''}
          </div>
        </div>
        <div class="flex gap-1 shrink-0">
          <button type="button" class="px-2 py-1 text-sm border rounded bg-white hover:bg-gray-100" onclick="moveReorderItem(this, -1)">↑</button>
          <button type="button" class="px-2 py-1 text-sm border rounded bg-white hover:bg-gray-100" onclick="moveReorderItem(this, 1)">↓</button>
        </div>
      </div>
    `;
  }).join('');

  if (typeof Sortable !== 'undefined') {
    new Sortable(list, {
      handle: '.reorder-handle',
      animation: 150,
      draggable: '.reorder-item[data-locked="0"]'
    });
  }
}

function moveReorderItem(button, direction) {
  const item = button.closest('.reorder-item');
  const list = document.getElementById('reorderBlocksList');
  if (!item || !list || item.dataset.locked === '1') return;

  const sibling = direction < 0 ? item.previousElementSibling : item.nextElementSibling;
  if (!sibling || sibling.dataset.locked === '1') return;

  if (direction < 0) {
    list.insertBefore(item, sibling);
  } else {
    list.insertBefore(sibling, item);
  }
}

function applyReorderBlocks() {
  const list = document.getElementById('reorderBlocksList');
  const container = document.getElementById('blocks-container');
  if (!list || !container) return;

  const ids = Array.from(list.querySelectorAll('.reorder-item')).map(item => item.dataset.blockId);
  const blockMap = new Map();

  Array.from(container.querySelectorAll(':scope > .block')).forEach(block => {
    blockMap.set(block.dataset.reorderId, block);
  });

  ids.forEach(id => {
    const block = blockMap.get(id);
    if (block) container.appendChild(block);
  });

  renumberBlocks();

  if (typeof window.autosaveTemplate === 'function') {
    try { window.autosaveTemplate(); } catch (_) {}
  }

  closeReorderModal();
}

function injectReorderButton() {
  const addStageButton = Array.from(document.querySelectorAll('button')).find(btn =>
    (btn.textContent || '').includes('Додати етап')
  );

  if (!addStageButton || document.getElementById('openReorderBlocksBtn')) return;

  const button = document.createElement('button');
  button.type = 'button';
  button.id = 'openReorderBlocksBtn';
  button.className = 'bg-indigo-500 text-white px-4 py-2 rounded mt-4 ml-2';
  button.textContent = '🔀 Змінити порядок';
  button.addEventListener('click', openReorderModal);

  addStageButton.insertAdjacentElement('afterend', button);
}

function addStage(data = {}, index = null) {
  // ✅ Не рендерим пустой блок из сохранённой структуры
  if (index !== null && isEmptyStageData(data)) {
    return;
  }

  const container = document.getElementById('blocks-container');
  const blockIndex = index !== null ? index : blockCounter++;

  const block = document.createElement('div');
  block.className = 'block bg-white p-4 rounded shadow mb-4 border relative';
  block.dataset.reorderId = `block-${Date.now()}-${Math.random().toString(16).slice(2)}`;

  block.innerHTML = `
    <div class="drag-handle cursor-move absolute left-2 top-2 text-gray-400" title="Перетягніть, щоб змінити порядок">⋮⋮</div>
    <button type="button" class="absolute top-2 right-2 text-red-500 hover:text-red-700 text-xl" onclick="deleteBlock(this)">✖</button>
    <h3 class="text-lg font-bold mb-2 pl-6">Блок №${blockIndex + 1}</h3>
    <input type="text" name="blocks[${blockIndex}][title]" placeholder="Заголовок етапу" class="w-full border rounded p-2 mb-2" value="${data.title || ''}" />
    <div class="rich-editor-wrapper mb-2">
      <input type="hidden" class="rich-hidden" name="blocks[${blockIndex}][description]" value="${escapeHtml(data.description || '')}" />
      <div class="rich-editor bg-white" data-placeholder="Опис етапу"></div>
    </div>

    <div class="subblocks mb-2"></div>
    <button type="button" onclick="addSubblock(this, ${blockIndex})" class="add-sub bg-blue-100 text-blue-700 px-2 py-1 rounded text-sm mb-2">+ Сабблок</button>

    <div class="tests mb-2"></div>
    <button type="button" onclick="addTest(this, ${blockIndex})" class="add-test bg-green-100 text-green-700 px-2 py-1 rounded text-sm">+ Тест</button>

    <div class="open-questions mt-2"></div>
    <button type="button" onclick="addOpenQuestion(this, ${blockIndex})" class="add-open bg-purple-100 text-purple-700 px-2 py-1 rounded text-sm">+ Відкрите питання</button>
  `;

  container.appendChild(block);

  initRichEditor(
    block.querySelector('.rich-editor-wrapper .rich-editor'),
    block.querySelector('.rich-editor-wrapper .rich-hidden'),
    data.description || ''
  );

  (data.subblocks || []).forEach((sub, i) => {
    if (isMeaningfulText(sub?.title) || isMeaningfulText(sub?.description)) {
      addSubblock(block.querySelector('.subblocks'), blockIndex, i, sub);
    }
  });

  (data.test?.questions || []).forEach((test, i) => {
    const hasQuestion = isMeaningfulText(test?.question);
    const hasAnswers = Array.isArray(test?.answers) && test.answers.some(a => isMeaningfulText(a?.value));
    if (hasQuestion || hasAnswers) {
      addTest(block.querySelector('.tests'), blockIndex, i, test);
    }
  });

  (data.open_questions || []).forEach((q, i) => {
    if (isMeaningfulText(q?.question)) {
      addOpenQuestion(block.querySelector('.open-questions'), blockIndex, i, q);
    }
  });

  const os = typeof window.onboarding_step === 'number'
    ? window.onboarding_step
    : parseInt(window.onboarding_step || '0', 10);

  if (!isNaN(os) && blockIndex < os) {
    lockBlock(block);
  }

  if (blockIndex >= blockCounter) blockCounter = blockIndex + 1;
}

function addSubblock(parentEl, blockIndex, subIndex = null, data = {}) {
  const container = typeof parentEl === 'object' && parentEl.classList && parentEl.classList.contains('subblocks')
    ? parentEl
    : parentEl.previousElementSibling;

  const idx = subIndex !== null ? subIndex : container.querySelectorAll('.subblock').length;

  const div = document.createElement('div');
  div.className = 'subblock border p-2 mb-2 rounded bg-blue-50 relative';
  div.innerHTML = `
    <button type="button" class="absolute top-1 right-2 text-red-500 hover:text-red-700 text-xl" onclick="deleteSubblock(this)">✖</button>
    <input type="text" name="blocks[${blockIndex}][subblocks][${idx}][title]" placeholder="Назва сабблоку" class="w-full mb-1 p-1 border rounded" value="${data.title || ''}" />
    <div class="rich-editor-wrapper">
      <input type="hidden" class="rich-hidden" name="blocks[${blockIndex}][subblocks][${idx}][description]" value="${escapeHtml(data.description || '')}" />
      <div class="rich-editor bg-white" data-placeholder="Опис сабблоку"></div>
    </div>
  `;
  container.appendChild(div);
  initRichEditor(
    div.querySelector('.rich-editor-wrapper .rich-editor'),
    div.querySelector('.rich-editor-wrapper .rich-hidden'),
    data.description || ''
  );
}

function addTest(parentEl, blockIndex, testIndex = null, data = {}) {
  const container = typeof parentEl === 'object' && parentEl.classList && parentEl.classList.contains('tests')
    ? parentEl
    : parentEl.previousElementSibling;

  const idx = testIndex !== null ? testIndex : container.querySelectorAll('.test').length;

  const div = document.createElement('div');
  div.className = 'test border p-2 mb-2 rounded bg-green-50 relative';
  div.innerHTML = `
    <button type="button" class="absolute top-1 right-2 text-red-500 hover:text-red-700 text-xl" onclick="deleteTest(this)">✖</button>
    <input type="text" name="blocks[${blockIndex}][test][questions][${idx}][question]" placeholder="Питання" class="w-full p-1 mb-1 border rounded" value="${data.question || ''}" />
    <div class="answers"></div>
    <button type="button" onclick="addAnswer(this, ${blockIndex}, ${idx})" class="bg-yellow-100 text-yellow-800 px-2 py-1 rounded text-xs">+ Відповідь</button>
  `;
  container.appendChild(div);

  if (!data.answers || data.answers.length === 0) {
    addAnswer(div.querySelector('.answers'), blockIndex, idx, 0);
    addAnswer(div.querySelector('.answers'), blockIndex, idx, 1);
  } else {
    data.answers.forEach((ans, i) => addAnswer(div.querySelector('.answers'), blockIndex, idx, i, ans));
  }
}

function addAnswer(parentEl, blockIndex, testIndex, answerIndex = null, data = {}) {
  const container = typeof parentEl === 'object' && parentEl.classList && parentEl.classList.contains('answers')
    ? parentEl
    : parentEl.previousElementSibling;

  const idx = answerIndex !== null ? answerIndex : container.querySelectorAll('.answer').length;

  const div = document.createElement('div');
  div.className = 'answer flex items-center gap-2 mb-1';
  div.innerHTML = `
    <button type="button" class="text-red-500 hover:text-red-700" onclick="deleteAnswer(this)">✖</button>
    <input type="text" name="blocks[${blockIndex}][test][questions][${testIndex}][answers][${idx}][value]" placeholder="Відповідь" class="flex-1 p-1 border rounded" value="${data?.value || ''}" />
    <label><input type="checkbox" name="blocks[${blockIndex}][test][questions][${testIndex}][answers][${idx}][correct]" ${data?.correct ? 'checked' : ''}/> Правильна</label>
  `;
  container.appendChild(div);
}

// 🆕 Открытый вопрос
function addOpenQuestion(parentEl, blockIndex, qIndex = null, data = {}) {
  const container = typeof parentEl === 'object' && parentEl.classList && parentEl.classList.contains('open-questions')
    ? parentEl
    : parentEl.previousElementSibling;

  const idx = qIndex !== null ? qIndex : container.querySelectorAll('.open-question').length;

  const div = document.createElement('div');
  div.className = 'open-question border p-2 mb-2 rounded bg-purple-50 relative';
  div.innerHTML = `
    <button type="button" class="absolute top-1 right-2 text-red-500 hover:text-red-700 text-xl" onclick="deleteOpenQuestion(this)">✖</button>
    <input type="text" name="blocks[${blockIndex}][open_questions][${idx}][question]" placeholder="Відкрите питання" class="w-full p-1 mb-1 border rounded" value="${data.question || ''}" />
  `;
  container.appendChild(div);
}

function parseStructure() {
  syncRichEditors();
  const blocks = [];

  document.querySelectorAll('.block').forEach((blockDiv) => {
    const block = {
      type: 'stage',
      title: blockDiv.querySelector('[name^="blocks"][name$="[title]"]')?.value || '',
      description: blockDiv.querySelector('[name^="blocks"][name$="[description]"]')?.value || '',
      subblocks: [],
      test: { questions: [] },
      open_questions: []
    };

    blockDiv.querySelectorAll('.subblock').forEach((subDiv) => {
      const title = subDiv.querySelector('[name$="[title]"]')?.value || '';
      const description = subDiv.querySelector('[name$="[description]"]')?.value || '';

      if (isMeaningfulText(title) || isMeaningfulText(description)) {
        block.subblocks.push({ title, description });
      }
    });

    blockDiv.querySelectorAll('.test').forEach((testDiv) => {
      const questionInput = testDiv.querySelector('[name$="[question]"]');
      const question = questionInput?.value || '';

      const answers = [];
      testDiv.querySelectorAll('.answer').forEach((aDiv) => {
        const value = aDiv.querySelector('[name$="[value]"]')?.value || '';
        const correct = aDiv.querySelector('[name$="[correct]"]')?.checked || false;
        if (isMeaningfulText(value)) {
          answers.push({ value, correct });
        }
      });

      if (isMeaningfulText(question) || answers.length > 0) {
        block.test.questions.push({
          question,
          multiple: false,
          answers
        });
      }
    });

    blockDiv.querySelectorAll('.open-question').forEach((qDiv) => {
      const question = qDiv.querySelector('[name$="[question]"]')?.value || '';
      if (isMeaningfulText(question)) {
        block.open_questions.push({ question });
      }
    });

    const hasTitle = isMeaningfulText(block.title);
    const hasDescription = isMeaningfulText(block.description);
    const hasSubblocks = block.subblocks.length > 0;
    const hasTests = block.test.questions.length > 0;
    const hasOpenQuestions = block.open_questions.length > 0;

    // ✅ Главное исправление: пустой блок не сохраняем
    if (hasTitle || hasDescription || hasSubblocks || hasTests || hasOpenQuestions) {
      blocks.push(block);
    }
  });

  return { blocks };
}

// ===== Initialize =====
window.addEventListener('DOMContentLoaded', () => {
  if (window.templateData && Array.isArray(window.templateData)) {
    window.templateData.forEach((block, i) => {
      if (!isEmptyStageData(block)) {
        addStage(block, i);
      }
    });
  }

  // Повторна ініціалізація rich editors після restore draft
  window.reinitRichEditorsFromDOM = reinitRichEditorsFromDOM;
  injectReorderButton();

  const container = document.getElementById('blocks-container');
  if (container && typeof Sortable !== 'undefined') {
    new Sortable(container, {
      handle: '.drag-handle',
      draggable: '.block:not(.locked)',
      animation: 150,
      onEnd: function () {
        renumberBlocks();
        if (typeof window.autosaveTemplate === 'function') {
          try { window.autosaveTemplate(); } catch (_) {}
        }
      }
    });
  }

  document.querySelector('form')?.addEventListener('submit', function () {
    const structure = parseStructure();
    document.getElementById('structure').value = JSON.stringify(structure.blocks);
  });

  window.addStage = addStage;
  window.addSubblock = addSubblock;
  window.addTest = addTest;
  window.addAnswer = addAnswer;
  window.addOpenQuestion = addOpenQuestion;
  window.openReorderModal = openReorderModal;
  window.closeReorderModal = closeReorderModal;
  window.applyReorderBlocks = applyReorderBlocks;
  window.moveReorderItem = moveReorderItem;
});