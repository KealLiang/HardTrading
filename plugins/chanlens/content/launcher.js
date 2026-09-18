/* ==========================================================================
 * launcher.js —— 站点侧的唯一残留工作
 *
 * 现在图表由 App 全屏页面绘制，注入脚本只剩一个用途：
 * 在你正在看某只股票时，认出代码，提供一个按钮把这只股带进 App。
 * 不做任何绘制、不注入面板样式，因此对宿主页面的干扰降到最低。
 * ========================================================================== */
'use strict';

(function () {
  'use strict';

  if (window.__chanlensLauncher) return;
  window.__chanlensLauncher = true;

  var info = CLAdapters.detect();
  if (!info.supported) {
    console.log('[ChanLens] 当前页面未识别到股票代码，未显示入口。' +
                '也可以直接点击工具栏的 ChanLens 图标打开。');
    return;
  }

  var btn = document.createElement('button');
  btn.className = 'cl-entry';
  btn.textContent = '缠';
  btn.title = '用 ChanLens 打开 ' + info.code + '（' + info.siteName + '）';
  btn.addEventListener('click', function (e) {
    e.preventDefault();
    btn.textContent = '…';
    chrome.runtime.sendMessage({ type: 'CL_OPEN_APP', code: info.code }, function () {
      btn.textContent = '缠';
    });
  });

  (document.body || document.documentElement).appendChild(btn);
  console.log('[ChanLens] 已识别 ' + info.code + '（' + info.siteName + '），点击右下角「缠」进入 App。');
})();
