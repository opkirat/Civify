// One sentence at a time; without JavaScript every card and form remains usable.
(() => {
  const deck = document.querySelector('.review-deck');
  if (!deck) return;
  const cards = [...deck.querySelectorAll(':scope > .claim')];
  if (!cards.length) return;
  const controls = document.getElementById('review-controls');
  const picker = document.getElementById('sentence-picker');
  const previous = document.getElementById('previous-sentence');
  const next = document.getElementById('next-sentence');
  const position = document.getElementById('review-position');
  let current = 0;
  cards.forEach((card, index) => {
    const option = document.createElement('option');
    option.value = index;
    option.textContent = `Sentence ${card.dataset.sentence}`;
    picker.append(option);
  });
  function show(index, updateHash = false) {
    current = Math.max(0, Math.min(index, cards.length - 1));
    cards.forEach((card, i) => card.hidden = i !== current);
    picker.value = current;
    position.textContent = `${current + 1} of ${cards.length} to review`;
    previous.disabled = current === 0;
    next.disabled = current === cards.length - 1;
    if (updateHash) history.replaceState(null, '', '#' + cards[current].id);
  }
  function fromHash() {
    const id = location.hash.slice(1);
    const index = cards.findIndex(card => card.id === id);
    if (index >= 0) show(index);
    else {
      const target = document.getElementById(id);
      if (target) {
        if (target.tagName === 'DETAILS') target.open = true;
        let parent = target.parentElement;
        while (parent) { if (parent.tagName === 'DETAILS') parent.open = true; parent = parent.parentElement; }
      }
    }
  }
  controls.hidden = false;
  show(0);
  fromHash();
  window.addEventListener('hashchange', fromHash);
  picker.addEventListener('change', () => show(Number(picker.value), true));
  previous.addEventListener('click', () => show(current - 1, true));
  next.addEventListener('click', () => show(current + 1, true));
})();
