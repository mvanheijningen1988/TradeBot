import { Injectable } from '@angular/core';
import { Subject, Observable } from 'rxjs';

export interface Toast {
  id: number;
  type: 'info' | 'success' | 'warning' | 'error';
  title: string;
  message: string;
  duration: number;
}

@Injectable({ providedIn: 'root' })
export class ToastService {
  private toasts$ = new Subject<Toast>();
  private nextId = 1;

  get toasts(): Observable<Toast> {
    return this.toasts$.asObservable();
  }

  info(title: string, message = '', duration = 5000): void {
    this._emit('info', title, message, duration);
  }

  success(title: string, message = '', duration = 4000): void {
    this._emit('success', title, message, duration);
  }

  warning(title: string, message = '', duration = 6000): void {
    this._emit('warning', title, message, duration);
  }

  error(title: string, message = '', duration = 8000): void {
    this._emit('error', title, message, duration);
  }

  private _emit(
    type: Toast['type'],
    title: string,
    message: string,
    duration: number
  ): void {
    this.toasts$.next({ id: this.nextId++, type, title, message, duration });
  }
}
