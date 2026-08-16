/* ============================================================
 * SKU Hunters · API 请求封装（client）
 * 纯 fetch：BASE、request、结构化错误归一化。
 * 只做纯请求，不改写任何 mock 常量；非 2xx 抛结构化错误（{status, code, message}）。
 * ============================================================ */

const BASE = '/api/v1';

/**
 * 统一请求封装：返回解析后的 JSON；非 2xx 抛出结构化错误。
 * 数据契约统一为 camelCase（与后端 loader / fixtures 对齐）。
 */
export async function request(url, opts = {}) {
  let res;
  try {
    res = await fetch(BASE + url, {
      headers: { 'Content-Type': 'application/json', ...opts.headers },
      ...opts,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
  } catch (e) {
    // 网络层失败（后端不在线 / 断网）：抛出统一错误，由调用方决定是否走演示数据
    const err = new Error('网络请求失败');
    err.code = 'NETWORK_ERROR';
    err.cause = e;
    throw err;
  }

  let data;
  try {
    data = await res.json();
  } catch {
    data = {};
  }

  if (!res.ok) {
    const err = new Error(data?.detail?.error?.message || `请求失败（${res.status}）`);
    err.status = res.status;
    err.code = data?.detail?.error?.code || 'HTTP_ERROR';
    err.detail = data?.detail;
    throw err;
  }
  return data;
}

export { BASE };
