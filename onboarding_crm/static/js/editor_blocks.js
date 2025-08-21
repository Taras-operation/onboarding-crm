let blockCounter = 0;

// ===== Helpers: lock completed blocks (read-only) =====
function lockBlock(blockDiv) {
  blockDiv.classList.add('locked', 'opacity-75');
  // Disable all inputs & buttons inside (except the global delete is also disabled)
  blockDiv.querySelectorAll('input, textarea, select, button').forEach(el => {
    // keep the drag handle visible but non-interactive for cursor clarity
    if (el.classList.contains('drag-handle')) return;
    el.disabled = true;
  });
  // Visual badge
  if (!blockDiv.querySelector('.lock-badge')) {
    const badge = document.createElement('div');
    badge.className = 'lock-badge absolute top-2 left-10 text-xs bg-gray-200 text-gray-700 px-2 py-1 rounded';
    badge.innerText = '🔒 Пройдено — редагування заблоковано';
    blockDiv.appendChild(badge);
  }
}

function unlockBlock(blockDiv) {
  blockDiv.classList.remove('locked', 'opacity-75');
  blockDiv.querySelectorAll('input, textarea, select, button').forEach(el => {
    if (el.classList.contains('drag-handle')) return;
    el.disabled = false;
  });
  const badge = blockDiv.querySelector('.lock-badge');
  if (badge) badge.remove();
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

function addStage(data = {}, index = null) {
  const container = document.getElementById('blocks-container');
  const blockIndex = index !== null ? index : blockCounter++;

  const block = document.createElement('div');
  block.className = 'block bg-white p-4 rounded shadow mb-4 border relative';

  block.innerHTML = `
    <div class="drag-handle cursor-move absolute left-2 top-2 text-gray-400" title="Перетягніть, щоб змінити порядок">⋮⋮</div>
    <button type="button" class="absolute top-2 right-2 text-red-500 hover:text-red-700 text-xl" onclick="deleteBlock(this)">✖</button>
    <h3 class="text-lg font-bold mb-2 pl-6">Блок №${blockIndex + 1}</h3>
    <input type="text" name="blocks[${blockIndex}][title]" placeholder="Заголовок етапу" class="w-full border rounded p-2 mb-2" value="${data.title || ''}" />
    <textarea name="blocks[${blockIndex}][description]" placeholder="Опис етапу" class="w-full border rounded p-2 mb-2">${data.description || ''}</textarea>

    <div class="subblocks mb-2"></div>
    <button type="button" onclick="addSubblock(this, ${blockIndex})" class="add-sub bg-blue-100 text-blue-700 px-2 py-1 rounded text-sm mb-2">+ Сабблок</button>

    <div class="tests mb-2"></div>
    <button type="button" onclick="addTest(this, ${blockIndex})" class="add-test bg-green-100 text-green-700 px-2 py-1 rounded text-sm">+ Тест</button>

    <div class="open-questions mt-2"></div>
    <button type="button" onclick="addOpenQuestion(this, ${blockIndex})" class="add-open bg-purple-100 text-purple-700 px-2 py-1 rounded text-sm">+ Відкрите питання</button>
  `;

  container.appendChild(block);

  // Загружаем сабблоки
  (data.subblocks || []).forEach((sub, i) => addSubblock(block.querySelector('.subblocks'), blockIndex, i, sub));

  // Загружаем тесты
  (data.test?.questions || []).forEach((test, i) => addTest(block.querySelector('.tests'), blockIndex, i, test));

  // Загружаем открытые вопросы
  (data.open_questions || []).forEach((q, i) => addOpenQuestion(block.querySelector('.open-questions'), blockIndex, i, q));

  // Apply locking based on initial onboarding_step only once (do not change on reorder)
  const os = typeof window.onboarding_step === 'number' ? window.onboarding_step : parseInt(window.onboarding_step || '0', 10);
  if (!isNaN(os) && blockIndex < os) {
    lockBlock(block);
  }

  if (blockIndex >= blockCounter) blockCounter = blockIndex + 1;
}

function addSubblock(parentEl, blockIndex, subIndex = null, data = {}) {
  const container = typeof parentEl === 'object' && parentEl.classList && parentEl.classList.contains('subblocks') ? parentEl : parentEl.previousElementSibling;
  const idx = subIndex !== null ? subIndex : container.querySelectorAll('.subblock').length;

  const div = document.createElement('div');
  div.className = 'subblock border p-2 mb-2 rounded bg-blue-50 relative';
  div.innerHTML = `
    <button type="button" class="absolute top-1 right-2 text-red-500 hover:text-red-700 text-xl" onclick="deleteSubblock(this)">✖</button>
    <input type="text" name="blocks[${blockIndex}][subblocks][${idx}][title]" placeholder="Назва сабблоку" class="w-full mb-1 p-1 border rounded" value="${data.title || ''}" />
    <textarea name="blocks[${blockIndex}][subblocks][${idx}][description]" placeholder="Опис сабблоку" class="w-full p-1 border rounded">${data.description || ''}</textarea>
  `;
  container.appendChild(div);
}

function addTest(parentEl, blockIndex, testIndex = null, data = {}) {
  const container = typeof parentEl === 'object' && parentEl.classList && parentEl.classList.contains('tests') ? parentEl : parentEl.previousElementSibling;
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

  // Автодобавляем 2 ответа по умолчанию
  if (!data.answers || data.answers.length === 0) {
    addAnswer(div.querySelector('.answers'), blockIndex, idx, 0);
    addAnswer(div.querySelector('.answers'), blockIndex, idx, 1);
  } else {
    data.answers.forEach((ans, i) => addAnswer(div.querySelector('.answers'), blockIndex, idx, i, ans));
  }
}

function addAnswer(parentEl, blockIndex, testIndex, answerIndex = null, data = {}) {
  const container = typeof parentEl === 'object' && parentEl.classList && parentEl.classList.contains('answers') ? parentEl : parentEl.previousElementSibling;
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
  const container = typeof parentEl === 'object' && parentEl.classList && parentEl.classList.contains('open-questions') ? parentEl : parentEl.previousElementSibling;
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
      block.subblocks.push({
        title: subDiv.querySelector('[name$="[title]"]')?.value || '',
        description: subDiv.querySelector('[name$="[description]"]')?.value || ''
      });
    });

    blockDiv.querySelectorAll('.test').forEach((testDiv) => {
      const questionInput = testDiv.querySelector('[name$="[question]"]');
      const question = questionInput?.value || '';

      const answers = [];
      testDiv.querySelectorAll('.answer').forEach((aDiv) => {
        const value = aDiv.querySelector('[name$="[value]"]')?.value || '';
        const correct = aDiv.querySelector('[name$="[correct]"]')?.checked || false;
        if (value.trim()) answers.push({ value, correct });
      });

      if (question) {
        block.test.questions.push({ question, multiple: false, answers });
      }
    });

    blockDiv.querySelectorAll('.open-question').forEach((qDiv) => {
      block.open_questions.push({
        question: qDiv.querySelector('[name$="[question]"]')?.value || ''
      });
    });

    blocks.push(block);
  });

  return { blocks };
}

// ===== Initialize =====
window.addEventListener('DOMContentLoaded', () => {
  // Render initial blocks
  if (window.templateData && Array.isArray(window.templateData)) {
    window.templateData.forEach((block, i) => addStage(block, i));
  }

  // Sortable for blocks container (only unlocked blocks are draggable)
  const container = document.getElementById('blocks-container');
  if (container && typeof Sortable !== 'undefined') {
    // eslint-disable-next-line no-undef
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
});