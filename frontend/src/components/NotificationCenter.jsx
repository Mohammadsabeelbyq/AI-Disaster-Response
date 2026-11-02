import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertOctagon,
  AlertTriangle,
  ArrowUpCircle,
  Bell,
  Check,
  CheckCheck,
  CheckCircle2,
  Clock,
  LoaderCircle,
  RefreshCw,
  SlidersHorizontal,
  Truck,
  X,
  XCircle,
} from 'lucide-react';
import {
  getUnreadCount,
  listNotifications,
  markAllNotificationsAsRead,
  markNotificationAsRead,
} from '../api/notifications.js';

function formatTimestamp(isoString) {
  if (!isoString) return '';
  const date = new Date(isoString);
  const now = new Date();
  const diffSec = Math.floor((now - date) / 1000);

  if (diffSec < 60) return 'Just now';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function getNotificationIcon(type) {
  switch (type) {
    case 'NEW_INCIDENT':
    case 'NEW_REPORT':
      return <AlertTriangle size={16} className="notif-icon notif-icon--alert" />;
    case 'INCIDENT_STATUS_CHANGED':
      return <RefreshCw size={16} className="notif-icon notif-icon--status" />;
    case 'INCIDENT_PRIORITY_CHANGED':
      return <SlidersHorizontal size={16} className="notif-icon notif-icon--priority" />;
    case 'PLAN_AWAITING_APPROVAL':
      return <Clock size={16} className="notif-icon notif-icon--approval" />;
    case 'PLAN_APPROVED':
      return <CheckCircle2 size={16} className="notif-icon notif-icon--approved" />;
    case 'PLAN_REJECTED':
      return <XCircle size={16} className="notif-icon notif-icon--rejected" />;
    case 'ASSIGNMENT_CONFIRMED':
      return <Truck size={16} className="notif-icon notif-icon--assigned" />;
    case 'OPERATION_FAILED':
      return <AlertOctagon size={16} className="notif-icon notif-icon--danger" />;
    default:
      return <Bell size={16} className="notif-icon notif-icon--default" />;
  }
}

export default function NotificationCenter({ user }) {
  const [isOpen, setIsOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [notifications, setNotifications] = useState([]);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [markingAll, setMarkingAll] = useState(false);
  const panelRef = useRef(null);
  const navigate = useNavigate();

  // Load unread count periodically
  useEffect(() => {
    let active = true;

    async function fetchCount() {
      try {
        const res = await getUnreadCount();
        if (active) setUnreadCount(res.unread_count || 0);
      } catch {
        // Silently tolerate background poll failures
      }
    }

    fetchCount();
    const interval = setInterval(fetchCount, 25000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  // Fetch notifications when panel opens or filter changes
  useEffect(() => {
    if (!isOpen) return;

    let active = true;
    setLoading(true);
    setError(null);

    listNotifications({ unreadOnly, limit: 40 })
      .then((items) => {
        if (active) setNotifications(items);
      })
      .catch((err) => {
        if (active) setError(err.message || 'Could not load notifications.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [isOpen, unreadOnly]);

  // Click outside listener to close dropdown
  useEffect(() => {
    function handleClickOutside(event) {
      if (panelRef.current && !panelRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    }

    function handleKeyDown(event) {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    }

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('keydown', handleKeyDown);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen]);

  async function handleMarkRead(event, notif) {
    event.stopPropagation();
    if (notif.is_read) return;

    try {
      await markNotificationAsRead(notif.id);
      setNotifications((current) =>
        current.map((item) => (item.id === notif.id ? { ...item, is_read: true } : item)),
      );
      setUnreadCount((c) => Math.max(0, c - 1));
    } catch {
      // Ignore click error
    }
  }

  async function handleMarkAll() {
    if (unreadCount === 0 || markingAll) return;
    setMarkingAll(true);
    try {
      await markAllNotificationsAsRead();
      setNotifications((current) => current.map((item) => ({ ...item, is_read: true })));
      setUnreadCount(0);
    } catch (err) {
      setError(err.message || 'Failed to mark all as read.');
    } finally {
      setMarkingAll(false);
    }
  }

  function handleNotificationClick(notif) {
    if (!notif.is_read) {
      markNotificationAsRead(notif.id).catch(() => {});
      setNotifications((current) =>
        current.map((item) => (item.id === notif.id ? { ...item, is_read: true } : item)),
      );
      setUnreadCount((c) => Math.max(0, c - 1));
    }

    setIsOpen(false);

    // Contextual navigation based on roles and targets
    if (user?.role === 'MANAGEMENT' || user?.role === 'ADMIN') {
      if (notif.incident_id) {
        navigate(`/review`);
      } else {
        navigate('/review');
      }
    }
  }

  return (
    <div className="notif-wrapper" ref={panelRef}>
      <button
        type="button"
        className={`notif-bell-btn ${unreadCount > 0 ? 'notif-bell-btn--has-unread' : ''}`}
        onClick={() => setIsOpen((prev) => !prev)}
        aria-label={`Notifications, ${unreadCount} unread`}
        aria-expanded={isOpen}
      >
        <Bell size={18} />
        {unreadCount > 0 && (
          <span className="notif-badge">{unreadCount > 99 ? '99+' : unreadCount}</span>
        )}
      </button>

      {isOpen && (
        <div className="notif-dropdown" role="region" aria-label="Notifications Panel">
          <div className="notif-dropdown__header">
            <div className="notif-dropdown__title">
              <strong>Notifications</strong>
              {unreadCount > 0 && (
                <span className="notif-pill notif-pill--active">{unreadCount} unread</span>
              )}
            </div>
            <div className="notif-dropdown__actions">
              {unreadCount > 0 && (
                <button
                  type="button"
                  className="notif-action-btn"
                  onClick={handleMarkAll}
                  disabled={markingAll}
                  title="Mark all notifications as read"
                >
                  {markingAll ? (
                    <LoaderCircle size={14} className="location-spinner" />
                  ) : (
                    <CheckCheck size={14} />
                  )}
                  <span>Mark all read</span>
                </button>
              )}
              <button
                type="button"
                className="notif-close-btn"
                onClick={() => setIsOpen(false)}
                aria-label="Close notifications"
              >
                <X size={16} />
              </button>
            </div>
          </div>

          <div className="notif-filters">
            <button
              type="button"
              className={`notif-filter-tab ${!unreadOnly ? 'notif-filter-tab--active' : ''}`}
              onClick={() => setUnreadOnly(false)}
            >
              All
            </button>
            <button
              type="button"
              className={`notif-filter-tab ${unreadOnly ? 'notif-filter-tab--active' : ''}`}
              onClick={() => setUnreadOnly(true)}
            >
              Unread
            </button>
          </div>

          <div className="notif-list-container">
            {loading ? (
              <div className="notif-state notif-state--loading">
                <LoaderCircle size={20} className="location-spinner" />
                <span>Loading notifications…</span>
              </div>
            ) : error ? (
              <div className="notif-state notif-state--error">
                <AlertOctagon size={20} />
                <span>{error}</span>
              </div>
            ) : notifications.length === 0 ? (
              <div className="notif-state notif-state--empty">
                <Bell size={24} opacity={0.35} />
                <span>{unreadOnly ? 'No unread notifications.' : 'No notifications yet.'}</span>
              </div>
            ) : (
              <ul className="notif-list">
                {notifications.map((notif) => (
                  <li
                    key={notif.id}
                    className={`notif-item ${!notif.is_read ? 'notif-item--unread' : ''}`}
                    onClick={() => handleNotificationClick(notif)}
                  >
                    <div className="notif-item__icon">{getNotificationIcon(notif.notification_type)}</div>
                    <div className="notif-item__content">
                      <div className="notif-item__top">
                        <span className="notif-item__title">{notif.title}</span>
                        <time className="notif-item__time">{formatTimestamp(notif.created_at)}</time>
                      </div>
                      <p className="notif-item__message">{notif.message}</p>
                    </div>
                    {!notif.is_read && (
                      <button
                        type="button"
                        className="notif-item__read-btn"
                        onClick={(e) => handleMarkRead(e, notif)}
                        title="Mark as read"
                        aria-label="Mark as read"
                      >
                        <Check size={14} />
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
