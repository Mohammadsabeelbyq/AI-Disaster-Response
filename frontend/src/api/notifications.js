import { request } from './client.js';

export function listNotifications({ unreadOnly = false, limit = 50, offset = 0 } = {}) {
  const query = new URLSearchParams({
    unread_only: String(unreadOnly),
    limit: String(limit),
    offset: String(offset),
  });
  return request(`/notifications?${query}`);
}

export function getUnreadCount() {
  return request('/notifications/unread-count');
}

export function markNotificationAsRead(notificationId) {
  return request(`/notifications/${encodeURIComponent(notificationId)}/read`, {
    method: 'PATCH',
  });
}

export function markAllNotificationsAsRead() {
  return request('/notifications/read-all', {
    method: 'PATCH',
  });
}
