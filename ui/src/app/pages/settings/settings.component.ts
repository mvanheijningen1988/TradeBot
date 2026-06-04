import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ExchangeService, Exchange } from '../../services/exchange.service';
import { AuthService } from '../../services/auth.service';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../../environments/environment';
import { DropdownComponent, DropdownOption } from '../../shared/dropdown/dropdown.component';

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [CommonModule, FormsModule, DropdownComponent],
  templateUrl: './settings.component.html',
  styleUrl: './settings.component.scss',
})
export class SettingsComponent implements OnInit {
  private readonly exchangeService = inject(ExchangeService);
  private readonly auth = inject(AuthService);
  private readonly http = inject(HttpClient);

  exchanges: Exchange[] = [];
  language: string | number = 'en';
  languageOptions: DropdownOption[] = [
    { value: 'en', label: 'English' },
    { value: 'nl', label: 'Nederlands' },
  ];
  timeDisplay: string | number = 'local';
  timeDisplayOptions: DropdownOption[] = [
    { value: 'local', label: 'Local Time' },
    { value: 'utc', label: 'UTC' },
  ];

  newExchange = { name: 'bitvavo', api_key: '', api_secret: '', rate_limit: 1000 };

  editingId: number | null = null;
  editForm = { api_key: '', api_secret: '', rate_limit: 1000 };

  ngOnInit(): void {
    this.loadExchanges();
    this.auth.currentUser$.subscribe((u) => {
      if (u) {
        this.language = u.language;
        this.timeDisplay = u.time_display;
      }
    });
  }

  loadExchanges(): void {
    this.exchangeService.list().subscribe((exs) => (this.exchanges = exs));
  }

  addExchange(): void {
    this.exchangeService.create(this.newExchange).subscribe(() => {
      this.loadExchanges();
      this.newExchange = { name: 'bitvavo', api_key: '', api_secret: '', rate_limit: 1000 };
    });
  }

  startEdit(ex: Exchange): void {
    this.editingId = ex.id;
    this.editForm = { api_key: '', api_secret: '', rate_limit: ex.rate_limit };
  }

  cancelEdit(): void {
    this.editingId = null;
  }

  saveEdit(ex: Exchange): void {
    const updates: { api_key?: string; api_secret?: string; rate_limit?: number } = {};
    if (this.editForm.api_key) updates.api_key = this.editForm.api_key;
    if (this.editForm.api_secret) updates.api_secret = this.editForm.api_secret;
    if (this.editForm.rate_limit !== ex.rate_limit) updates.rate_limit = this.editForm.rate_limit;
    if (Object.keys(updates).length === 0) {
      this.editingId = null;
      return;
    }
    this.exchangeService.update(ex.id, updates).subscribe(() => {
      this.editingId = null;
      this.loadExchanges();
    });
  }

  deleteExchange(ex: Exchange): void {
    if (confirm(`Delete exchange "${ex.name}"?`)) {
      this.exchangeService.delete(ex.id).subscribe(() => this.loadExchanges());
    }
  }

  updateLanguage(): void {
    this.http
      .put(`${environment.apiUrl}/settings/language`, { language: this.language })
      .subscribe(() => this.auth.loadUser());
  }

  updateTimeDisplay(): void {
    this.http
      .put(`${environment.apiUrl}/settings/time-display`, {
        time_display: this.timeDisplay,
      })
      .subscribe(() => this.auth.loadUser());
  }
}
