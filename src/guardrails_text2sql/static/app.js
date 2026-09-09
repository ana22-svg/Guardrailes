const state = { current: null };
const $ = (selector) => document.querySelector(selector);

function showNotice(message, error = false) {
  const notice = $('#notice');
  notice.textContent = message;
  notice.className = `notice${error ? ' error' : ''}`;
  notice.hidden = false;
}

function renderRows(rows) {
  const wrap = $('#table-wrap');
  if (!rows || rows.length === 0) {
    wrap.innerHTML = '<div class="empty-state">The query returned no rows.</div>';
    return;
  }
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  wrap.innerHTML = `<table><thead><tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join('')}</tr></thead><tbody>${rows.map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(row[column])}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}

function renderResult(result) {
  state.current = result;
  $('#result-title').textContent = result.question;
  $('#sql-output code').textContent = result.sql || '-- No executable SQL returned';
  $('#explanation').textContent = result.explanation || result.error || 'Clarification is required before a query can run.';
  $('#result-count').textContent = result.rows ? `${result.rows.length} row${result.rows.length === 1 ? '' : 's'}` : 'No rows';
  $('#execution-meta').textContent = result.retry_count ? `${result.retry_count} retry${result.retry_count === 1 ? '' : 'ies'}` : 'first attempt';
  $('#copy-sql').disabled = !result.sql;
  $('#feedback-yes').disabled = !result.query_id;
  $('#feedback-no').disabled = !result.query_id;
  renderRows(result.rows);
  renderConfidence(result.validation, result.confidence);
  if (result.error) showNotice(result.error, true);
  else if (result.clarification) showNotice(`Clarification needed for: ${result.clarification.term}`);
  else if (result.guardrail_warnings && result.guardrail_warnings.length) showNotice(result.guardrail_warnings.join(' '));
  else $('#notice').hidden = true;
}

function renderConfidence(validation, fallback) {
  const score = validation ? validation.confidence : fallback || 0;
  const percent = Math.round(score * 100);
  const ring = $('#confidence-ring');
  ring.style.background = `conic-gradient(var(--green) ${percent * 3.6}deg, var(--mint) 0deg)`;
  $('#confidence-value').textContent = validation ? `${percent}%` : '--';
  $('#confidence-label').textContent = validation ? (validation.passed ? 'High-confidence result' : 'Needs review') : 'Awaiting result';
  $('#confidence-reason').textContent = validation?.reasons?.join(' ') || 'Signals appear after execution.';
  $('#signals').innerHTML = validation ? validation.signals.map((signal) => `<div class="signal"><span class="signal-name">${escapeHtml(signal.name.replaceAll('_', ' '))}</span><strong class="${signal.passed ? 'pass' : 'fail'}">${Math.round(signal.score * 100)}%</strong></div>`).join('') : '';
}

async function runQuery(question) {
  showNotice('Running through schema selection, guardrails, and validation...');
  const response = await fetch('/v1/query', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question }) });
  if (!response.ok) throw new Error((await response.json()).detail || 'The query request failed.');
  renderResult(await response.json());
  await loadHistory();
}

async function loadHistory() {
  const response = await fetch('/v1/history?limit=8');
  if (!response.ok) return;
  const data = await response.json();
  $('#history').innerHTML = data.items.length ? data.items.map((item) => `<button class="history-item" data-query-id="${item.query_id}"><strong>${escapeHtml(item.question)}</strong><small>${Math.round((item.confidence || 0) * 100)}% confidence</small></button>`).join('') : '<div class="empty-state compact">No queries in this session.</div>';
  document.querySelectorAll('.history-item').forEach((button) => button.addEventListener('click', () => loadHistoryItem(data.items.find((item) => item.query_id === button.dataset.queryId))));
}

function loadHistoryItem(item) { if (item) renderResult(item); }

async function sendFeedback(correct) {
  if (!state.current?.query_id) return;
  const response = await fetch('/v1/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query_id: state.current.query_id, correct }) });
  if (response.ok) showNotice(correct ? 'Marked correct and stored for review.' : 'Marked for review as an incorrect result.');
}

function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[character])); }

$('#query-form').addEventListener('submit', async (event) => { event.preventDefault(); try { await runQuery($('#question').value.trim()); } catch (error) { showNotice(error.message, true); } });
$('#question').addEventListener('keydown', (event) => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') $('#query-form').requestSubmit(); });
document.querySelectorAll('[data-question]').forEach((button) => button.addEventListener('click', () => { $('#question').value = button.dataset.question; $('#question').focus(); }));
$('#refresh-history').addEventListener('click', loadHistory);
$('#copy-sql').addEventListener('click', async () => { await navigator.clipboard.writeText(state.current?.sql || ''); showNotice('SQL copied to clipboard.'); });
$('#feedback-yes').addEventListener('click', () => sendFeedback(true));
$('#feedback-no').addEventListener('click', () => sendFeedback(false));
loadHistory();
