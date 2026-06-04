import { Component, OnDestroy, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ExchangeService, Exchange } from '../../services/exchange.service';
import { AuthService } from '../../services/auth.service';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../../environments/environment';
import { DropdownComponent, DropdownOption } from '../../shared/dropdown/dropdown.component';
import {
  NewsSettingsService,
  NewsFeed,
  CoinMapping,
  WordFilter,
} from '../../services/news-settings.service';
import { SignalsService } from '../../services/signals.service';

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [CommonModule, FormsModule, DropdownComponent],
  templateUrl: './settings.component.html',
  styleUrl: './settings.component.scss',
})
export class SettingsComponent implements OnInit, OnDestroy {
  private readonly exchangeService = inject(ExchangeService);
  private readonly auth = inject(AuthService);
  private readonly http = inject(HttpClient);
  private readonly newsSvc = inject(NewsSettingsService);
  private readonly signalsSvc = inject(SignalsService);
  private pollTimer?: ReturnType<typeof setInterval>;

  activeTab: 'general' | 'news' = 'general';

  // ── General tab ───────────────────────────────────────────────
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

  // ── News tab ──────────────────────────────────────────────────
  feeds: NewsFeed[] = [];
  newFeed = { name: '', url: '' };

  coinMappings: CoinMapping[] = [];
  newCoinMapping = { name: '', symbol: '', ambiguous: false };
  editingMappingId: number | null = null;
  editMappingForm = { name: '', symbol: '', ambiguous: false };

  wordFilters: WordFilter[] = [];
  newWord = '';
  newWordType: 'include' | 'exclude' = 'exclude';

  minConfidence = 0;
  minConfidenceSaving = false;
  signalsRefreshing = false;

  ngOnInit(): void {
    this.loadExchanges();
    this.auth.currentUser$.subscribe((u) => {
      if (u) {
        this.language = u.language;
        this.timeDisplay = u.time_display;
      }
    });
  }

  ngOnDestroy(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = undefined;
    }
  }

  private waitForEngineCycle(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = undefined;
    }

    const checkStatus = () => {
      this.signalsSvc.getStatus().subscribe({
        next: (status) => {
          if (!status.processing) {
            if (this.pollTimer) {
              clearInterval(this.pollTimer);
              this.pollTimer = undefined;
            }
            this.signalsRefreshing = false;
            this.signalsSvc.refresh$.next();
          }
        },
        error: () => {
          if (this.pollTimer) {
            clearInterval(this.pollTimer);
            this.pollTimer = undefined;
          }
          this.signalsRefreshing = false;
        },
      });
    };

    checkStatus();
    this.pollTimer = setInterval(checkStatus, 1000);
  }

  switchTab(tab: 'general' | 'news'): void {
    this.activeTab = tab;
    if (tab === 'news') {
      this.loadFeeds();
      this.loadCoinMappings();
      this.loadWordFilters();
      this.loadParams();
    }
  }

  // ── General tab methods ────────────────────────────────────────
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

  // ── News tab — Feeds ────────────────────────────────────────────
  loadFeeds(): void {
    this.newsSvc.getFeeds().subscribe((f) => (this.feeds = f));
  }

  addFeed(): void {
    if (!this.newFeed.name || !this.newFeed.url) return;
    this.newsSvc.createFeed(this.newFeed.name, this.newFeed.url).subscribe(() => {
      this.newFeed = { name: '', url: '' };
      this.loadFeeds();
    });
  }

  toggleFeed(feed: NewsFeed): void {
    this.newsSvc
      .updateFeed(feed.id, { enabled: !feed.enabled })
      .subscribe(() => this.loadFeeds());
  }

  deleteFeed(feed: NewsFeed): void {
    if (confirm(`Delete feed "${feed.name}"?`)) {
      this.newsSvc.deleteFeed(feed.id).subscribe(() => this.loadFeeds());
    }
  }

  // ── News tab — Coin mappings ────────────────────────────────────
  loadCoinMappings(): void {
    this.newsSvc.getCoinMappings().subscribe((m) => (this.coinMappings = m));
  }

  addCoinMapping(): void {
    if (!this.newCoinMapping.name || !this.newCoinMapping.symbol) return;
    this.newsSvc
      .createCoinMapping(
        this.newCoinMapping.name,
        this.newCoinMapping.symbol.toUpperCase(),
        this.newCoinMapping.ambiguous
      )
      .subscribe(() => {
        this.newCoinMapping = { name: '', symbol: '', ambiguous: false };
        this.loadCoinMappings();
      });
  }

  startEditMapping(m: CoinMapping): void {
    this.editingMappingId = m.id;
    this.editMappingForm = {
      name: m.name,
      symbol: m.symbol,
      ambiguous: m.ambiguous,
    };
  }

  saveEditMapping(m: CoinMapping): void {
    this.newsSvc.updateCoinMapping(m.id, this.editMappingForm).subscribe(() => {
      this.editingMappingId = null;
      this.loadCoinMappings();
    });
  }

  cancelEditMapping(): void {
    this.editingMappingId = null;
  }

  deleteCoinMapping(m: CoinMapping): void {
    if (confirm(`Delete mapping for "${m.name}"?`)) {
      this.newsSvc.deleteCoinMapping(m.id).subscribe(() => this.loadCoinMappings());
    }
  }

  // ── News tab — Word filters ─────────────────────────────────────
  loadWordFilters(): void {
    this.newsSvc.getWordFilters().subscribe((f) => (this.wordFilters = f));
  }

  get includeWords(): WordFilter[] {
    return this.wordFilters.filter((f) => f.filter_type === 'include');
  }

  get excludeWords(): WordFilter[] {
    return this.wordFilters.filter((f) => f.filter_type === 'exclude');
  }

  addWordFilter(): void {
    if (!this.newWord.trim()) return;
    this.newsSvc.createWordFilter(this.newWord.trim(), this.newWordType).subscribe(() => {
      this.newWord = '';
      this.loadWordFilters();
    });
  }

  deleteWordFilter(f: WordFilter): void {
    this.newsSvc.deleteWordFilter(f.id).subscribe(() => this.loadWordFilters());
  }

  // ── News tab — Engine parameters ────────────────────────────────
  loadParams(): void {
    this.newsSvc.getParams().subscribe((p) => {
      this.minConfidence = p.min_confidence;
    });
  }

  saveMinConfidence(): void {
    this.minConfidenceSaving = true;
    this.newsSvc
      .updateParams({ min_confidence: this.minConfidence })
      .subscribe({
        next: () => {
          this.minConfidenceSaving = false;
          this.signalsRefreshing = true;
          this.waitForEngineCycle();
        },
        error: () => {
          this.minConfidenceSaving = false;
          this.signalsRefreshing = false;
        },
      });
  }
}
