import { request } from './client.js';

export function listPriorityConfigs() {
  return request('/priority-configs');
}

export function getActivePriorityConfig() {
  return request('/priority-configs/active');
}

export function createPriorityConfig(configuration) {
  return request('/priority-configs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(configuration),
  });
}