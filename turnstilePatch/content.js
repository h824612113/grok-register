// Turnstile 自动化扩展
// 自动解决 Cloudflare Turnstile 验证
(function() {
    'use strict';
    
    // 监听 Turnstile iframe 出现
    const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
            for (const node of mutation.addedNodes) {
                if (node.nodeType === 1) {
                    // 检查是否是 Turnstile iframe
                    if (node.tagName === 'IFRAME' && node.src && node.src.includes('turnstile')) {
                        console.log('[Turnstile Patch] 检测到 Turnstile iframe');
                        // 等待 iframe 加载后自动点击
                        setTimeout(() => {
                            try {
                                // 尝试获取 iframe 内容
                                const iframeDoc = node.contentDocument || node.contentWindow.document;
                                const checkbox = iframeDoc.querySelector('input[type="checkbox"]');
                                if (checkbox) {
                                    console.log('[Turnstile Patch] 找到 checkbox，自动点击');
                                    checkbox.click();
                                }
                            } catch (e) {
                                console.log('[Turnstile Patch] 无法访问 iframe 内容（跨域）');
                            }
                        }, 2000);
                    }
                }
            }
        }
    });
    
    observer.observe(document.documentElement, {
        childList: true,
        subtree: true
    });
    
    // 页面加载时检查
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            const iframes = document.querySelectorAll('iframe[src*="turnstile"]');
            if (iframes.length > 0) {
                console.log('[Turnstile Patch] 页面加载时检测到 Turnstile iframe');
            }
        });
    }
})();
