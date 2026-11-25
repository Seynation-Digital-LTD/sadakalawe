/* Pay Now / Credit toggle + payment-method grid (New and Edit document). */
(function () {
  const timingOpts = document.querySelectorAll('.payment-opt');
  const methodOpts = document.querySelectorAll('.pay-method-opt');
  const methodWrap = document.getElementById('method-wrap');
  const dueSec     = document.getElementById('due-date-section');
  const payTypeHid = document.getElementById('payment_type');
  if (!payTypeHid) return;

  function sync() {
    const timing = document.querySelector('input[name="_timing"]:checked')?.value;
    const method = document.querySelector('input[name="_method"]:checked')?.value || 'cash';
    payTypeHid.value = timing === 'credit' ? 'credit' : method;
  }
  timingOpts.forEach(opt => opt.addEventListener('click', () => {
    timingOpts.forEach(o => o.classList.remove('active'));
    opt.classList.add('active');
    opt.querySelector('input').checked = true;
    const credit = opt.querySelector('input').value === 'credit';
    methodWrap.style.display = credit ? 'none' : '';
    dueSec.style.display     = credit ? '' : 'none';
    sync();
  }));
  methodOpts.forEach(opt => opt.addEventListener('click', () => {
    methodOpts.forEach(o => o.classList.remove('active'));
    opt.classList.add('active');
    opt.querySelector('input').checked = true;
    sync();
  }));
  sync();
})();
