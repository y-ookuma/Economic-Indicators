// 「YouTuber」タブ：各チャンネルの最新動画タイトル（RSS から加工せずに表示）
import { esc } from './util.js';

export function show(analysis) {
  const cards = analysis.youtube.map(ch => {
    const link = `https://www.youtube.com/channel/${esc(ch.channel_id)}`;
    if (ch.error || !ch.videos?.length) {
      return `<article class="card yt-card"><h3><a href="${link}" target="_blank" rel="noopener">${esc(ch.name)}</a></h3>
        <p class="errors">最新動画を取得できませんでした${ch.error ? `（${esc(ch.error)}）` : ''}</p></article>`;
    }
    const [latest, ...rest] = ch.videos;
    const more = rest.length ? `<details><summary>最近の動画（${rest.length}件）</summary><ul class="yt-list">${rest.map(v =>
      `<li><a href="${esc(v.url)}" target="_blank" rel="noopener">${esc(v.title)}</a> <small>${v.date}</small></li>`).join('')}</ul></details>` : '';
    return `<article class="card yt-card">
      <h3><a href="${link}" target="_blank" rel="noopener">${esc(ch.name)}</a></h3>
      <p class="yt-latest"><span class="yt-date">${latest.date}</span>
        <a href="${esc(latest.url)}" target="_blank" rel="noopener">${esc(latest.title)}</a></p>
      ${more}
    </article>`;
  }).join('');
  document.getElementById('youtubeBody').innerHTML = `
    <div class="cards">${cards}</div>
    <p class="sub">各チャンネルの最新動画タイトルを YouTube の RSS からそのまま表示しています（要約・加工なし）。内容は各発信者の見解です。
    チャンネルは <code>config/youtubers.json</code> で変更できます。取得: ${new Date(analysis.updated_at).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' })} JST</p>`;
}
