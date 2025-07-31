let blockCounter = 0;

// 🔄 Перенумерация блоков
function renumberBlocks() {
  const blocks = document.querySelectorAll('#blocks-container > .block');
  blocks.forEach((blockDiv, i) => {
    blockDiv.querySelector('h3').innerText = `Блок №${i + 1}`;
    blockDiv.querySelectorAll('input, textarea, select').forEach(input => {
      if (input.name.includes('blocks')) {
        input.name = input.name.replace(/blocks\[\d+\]/, `blocks[${i}]`);
      }
    });
    renumberSubblocks(blockDiv, i);
    renumberTests(blockDiv, i);
  });
  blockCounter = blocks.length;
}

// 🔄 Перенумерация сабблоков
function renumberSubblocks(blockDiv, blockIndex) {
  const subblocks = blockDiv.querySelectorAll('.subblock');
  subblocks.forEach((subDiv, i) => {
    subDiv.querySelectorAll('input, textarea').forEach(input => {
      if (input.name.includes('subblocks')) {
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
      if (input.name.includes('questions')) {
        input.name = input.name.replace(/questions\]\[\d+\]/, `questions][${i}]`);
      }
    });
    renumberAnswers(testDiv, blockIndex, i);
  });
}

// 🔄 Перенумерация ответов
function renumberAnswers(testDiv, blockIndex, testIndex) {
  const answers = testDiv.querySelectorAll('.answer');
  answers.forEach((aDiv, i) => {
    aDiv.querySelectorAll('input').forEach(input => {
      if (input.name.includes('answers')) {
        input.name = input.name.replace(/answers\]\[\d+\]/, `answers][${i}]`);
      }
    });
  });
}

// ❌ Удаление блока
function deleteBlock(btn) {
  btn.closest('.block').remove();
  renumberBlocks();
}

// ❌ Удаление сабблока
function deleteSubblock(btn) {
  const blockDiv = btn.closest('.block');
  btn.closest('.subblock').remove();
  renumberSubblocks(blockDiv);
}

// ❌ Удаление теста
function deleteTest(btn) {
  const blockDiv = btn.closest('.block');
  btn.closest('.test').remove();
  renumberTests(blockDiv);
}

// ❌ Удаление ответа
function deleteAnswer(btn) {
  const testDiv = btn.closest('.test');
  btn.closest('.answer').remove();
  renumberAnswers(testDiv);
}

function addStage(data = {}, index = null) {
  const container = document.getElementById('blocks-container');
  const blockIndex = index !== null ? index : blockCounter++;

  const block = document.createElement('div');
  block.className = "block bg-white p-4 rounded shadow mb-4 border relative";

  block.innerHTML = `
    <button type="button" class="absolute top-2 right-2 text-red-500 hover:text-red-700 text-xl" onclick="deleteBlock(this)">✖</button>
    <h3 class="text-lg font-bold mb-2">Блок №${blockIndex + 1}</h3>
    <input type="text" name="blocks[${blockIndex}][title]" placeholder="Заголовок етапу" class="w-full border rounded p-2 mb-2" value="${data.title || ''}" />
    <textarea name="blocks[${blockIndex}][description]" placeholder="Опис етапу" class="w-full border rounded p-2 mb-2">${data.description || ''}</textarea>

    <div class="subblocks mb-2"></div>
    <button type="button" onclick="addSubblock(this, ${blockIndex})" class="bg-blue-100 text-blue-700 px-2 py-1 rounded text-sm mb-2">+ Сабблок</button>

    <div class="tests"></div>
    <button type="button" onclick="addTest(this, ${blockIndex})" class="bg-green-100 text-green-700 px-2 py-1 rounded text-sm">+ Тест</button>
  `;

  container.appendChild(block);

  const subblocks = data.subblocks || [];
  subblocks.forEach((sub, i) => addSubblock(block.querySelector('.subblocks'), blockIndex, i, sub));

  const questions = data.test?.questions || [];
  questions.forEach((test, i) => addTest(block.querySelector('.tests'), blockIndex, i, test));

  if (typeof window.onboarding_step !== 'undefined' && blockIndex < window.onboarding_step) {
    block.querySelectorAll('input, textarea, button, select').forEach(el => {
      el.disabled = true;
    });
  }

  if (blockIndex >= blockCounter) {
    blockCounter = blockIndex + 1;
  }

  // ✅ Автозбереження
  if (window.templateId && window.templateId !== 'null') {
    const tempStructure = parseStructure();
    fetch(`/autosave_template/${window.templateId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ structure: tempStructure.blocks })
    })
    .then(res => res.json())
    .then(data => console.log("✔️ Автозбереження успішне"))
    .catch(err => console.warn("⚠️ Помилка автозбереження", err));
  }
}

function addSubblock(parentEl, blockIndex, subIndex = null, data = {}) {
  const container = typeof parentEl === 'object' && parentEl.classList?.contains('subblocks') ? parentEl : parentEl.previousElementSibling;
  const subblocks = container.querySelectorAll('.subblock');
  const idx = subIndex !== null ? subIndex : subblocks.length;

  const div = document.createElement('div');
  div.className = "subblock border p-2 mb-2 rounded bg-blue-50 relative";
  div.innerHTML = `
    <button type="button" class="absolute top-1 right-2 text-red-500 hover:text-red-700 text-xl" onclick="deleteSubblock(this)">✖</button>
    <input type="text" name="blocks[${blockIndex}][subblocks][${idx}][title]" placeholder="Назва сабблоку" class="w-full mb-1 p-1 border rounded" value="${data.title || ''}" />
    <textarea name="blocks[${blockIndex}][subblocks][${idx}][description]" placeholder="Опис сабблоку" class="w-full p-1 border rounded">${data.description || ''}</textarea>
  `;
  container.appendChild(div);
}

function addTest(parentEl, blockIndex, testIndex = null, data = {}) {
  const container = typeof parentEl === 'object' && parentEl.classList?.contains('tests') ? parentEl : parentEl.previousElementSibling;
  const tests = container.querySelectorAll('.test');
  const idx = testIndex !== null ? testIndex : tests.length;

  const div = document.createElement('div');
  div.className = "test border p-2 mb-2 rounded bg-green-50 relative";
  div.innerHTML = `
    <button type="button" class="absolute top-1 right-2 text-red-500 hover:text-red-700 text-xl" onclick="deleteTest(this)">✖</button>
    <input type="text" name="blocks[${blockIndex}][test][questions][${idx}][question]" placeholder="Питання" class="w-full p-1 mb-1 border rounded" value="${data.question || ''}" />
    <div class="answers"></div>
    <button type="button" onclick="addAnswer(this, ${blockIndex}, ${idx})" class="bg-yellow-100 text-yellow-800 px-2 py-1 rounded text-xs">+ Відповідь</button>
  `;
  container.appendChild(div);

  const answers = data.answers || [];
  if (answers.length === 0) {
    addAnswer(div.querySelector('.answers'), blockIndex, idx, 0, {});
    addAnswer(div.querySelector('.answers'), blockIndex, idx, 1, {});
  } else {
    answers.forEach((ans, aIndex) => addAnswer(div.querySelector('.answers'), blockIndex, idx, aIndex, ans));
  }
}

function addAnswer(parentEl, blockIndex, testIndex, answerIndex = null, data = {}) {
  const container = typeof parentEl === 'object' && parentEl.classList?.contains('answers') ? parentEl : parentEl.previousElementSibling;
  const answers = container.querySelectorAll('.answer');
  const idx = answerIndex !== null ? answerIndex : answers.length;

  const div = document.createElement('div');
  div.className = "answer flex items-center gap-2 mb-1";
  div.innerHTML = `
    <button type="button" class="text-red-500 hover:text-red-700" onclick="deleteAnswer(this)">✖</button>
    <input type="text" name="blocks[${blockIndex}][test][questions][${testIndex}][answers][${idx}][value]" placeholder="Відповідь" class="flex-1 p-1 border rounded" value="${data.value || ''}" />
    <label><input type="checkbox" name="blocks[${blockIndex}][test][questions][${testIndex}][answers][${idx}][correct]" ${data.correct ? 'checked' : ''}/> Правильна</label>
  `;
  container.appendChild(div);
}

function parseStructure() {
  const blocks = [];
  document.querySelectorAll('.block').forEach((blockDiv, blockIndex) => {
    const block = {
      type: 'stage',
      title: blockDiv.querySelector('[name^="blocks"][name$="[title]"]')?.value || '',
      description: blockDiv.querySelector('[name^="blocks"][name$="[description]"]')?.value || '',
      subblocks: [],
      test: { questions: [] }
    };

    blockDiv.querySelectorAll('.subblock').forEach((subDiv) => {
      const subblock = {
        title: subDiv.querySelector('[name$="[title]"]')?.value || '',
        description: subDiv.querySelector('[name$="[description]"]')?.value || ''
      };
      block.subblocks.push(subblock);
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

      if (question && answers.length > 0) {
        block.test.questions.push({ question, multiple: false, answers });
      }
    });

    blocks.push(block);
  });

  return { blocks };
}

window.addEventListener('DOMContentLoaded', () => {
  if (window.templateData && Array.isArray(window.templateData)) {
    window.templateData.forEach((block, i) => addStage(block, i));
  }

  document.querySelector('form')?.addEventListener('submit', function () {
    const structure = parseStructure();
    document.getElementById('structure').value = JSON.stringify(structure.blocks);
  });

  window.addStage = addStage;
  window.addSubblock = addSubblock;
  window.addTest = addTest;
  window.addAnswer = addAnswer;
});