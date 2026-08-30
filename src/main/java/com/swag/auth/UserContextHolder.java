package com.swag.auth;

/**
 * 保存当前请求解析出的登录用户 ID。
 * <p>
 * 与 {@code AuditContextHolder} 一样基于 ThreadLocal，仅适用于同步调用链；
 * 工具方法在流式（Reactor）调用下应改用 ToolContext 传递用户 ID。
 */
public final class UserContextHolder {

    private static final ThreadLocal<Long> USER_ID = new ThreadLocal<>();

    private UserContextHolder() {
    }

    public static Long currentUserId() {
        return USER_ID.get();
    }

    public static void set(Long userId) {
        if (userId == null) {
            USER_ID.remove();
        }
        else {
            USER_ID.set(userId);
        }
    }

    public static void clear() {
        USER_ID.remove();
    }
}
