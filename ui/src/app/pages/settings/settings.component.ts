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
  private exchangeService = inject(ExchangeService);
  private auth = inject(AuthService);
  private http = inject(HttpClient);

  exchanges: Exchange[] = [];
  language: string | number = 'en';
  languageOptions: DropdownOption[] = [
    { value: 'en', label: 'English' },
    { value: 'nl', label: 'Nederlands' },
  ];

  newExchange = { name: 'bitvavo', api_key: '', api_secret: '', rate_limit: 1000 };

  ngOnInit(): void {
    this.loadExchanges();
    this.auth.currentUser$.subscribe((u) => {
      if (u) this.language = u.language;
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

  deleteExchange(ex: Exchange): void {
    if (confirm(`Delete exchange "${ex.name}"?`)) {
      this.exchangeService.delete(ex.id).subscribe(() => this.loadExchanges());
    }
  }

  updateLanguage(): void {
    this.http
      .put(`${environment.apiUrl}/settings/language`, { language: this.language })
      .subscribe();
  }
}
