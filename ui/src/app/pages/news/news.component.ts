import { Component, OnDestroy, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Subscription, timer } from 'rxjs';
import {
  DropdownComponent,
  DropdownOption,
} from '../../shared/dropdown/dropdown.component';
import { AppDateTimePipe } from '../../shared/pipes/app-datetime.pipe';
import {
  NewsArticle,
  NewsOverview,
  NewsSettingsService,
} from '../../services/news-settings.service';

@Component({
  selector: 'app-news',
  standalone: true,
  imports: [CommonModule, DropdownComponent, AppDateTimePipe],
  templateUrl: './news.component.html',
  styleUrl: './news.component.scss',
})
export class NewsComponent implements OnInit, OnDestroy {
  private readonly newsService = inject(NewsSettingsService);
  private refreshSub?: Subscription;

  overview: NewsOverview | null = null;
  articles: NewsArticle[] = [];
  loading = false;
  selectedSentiment: string | number = 'all';

  sentimentOptions: DropdownOption[] = [
    { value: 'all', label: 'All sentiment' },
    { value: 'positive', label: 'Positive' },
    { value: 'neutral', label: 'Neutral' },
    { value: 'negative', label: 'Negative' },
  ];

  ngOnInit(): void {
    this.refreshSub = timer(0, 30_000).subscribe(() => this.loadNews(true));
  }

  ngOnDestroy(): void {
    this.refreshSub?.unsubscribe();
  }

  get filteredArticles(): NewsArticle[] {
    if (this.selectedSentiment === 'all') {
      return this.articles;
    }
    return this.articles.filter((article) => {
      const label = article.sentiment_label;
      if (this.selectedSentiment === 'positive') {
        return label === 'bullish' || article.sentiment_score > 0.15;
      }
      if (this.selectedSentiment === 'negative') {
        return label === 'bearish' || article.sentiment_score < -0.15;
      }
      return label === 'neutral' || Math.abs(article.sentiment_score) <= 0.15;
    });
  }

  get indicatorClass(): string {
    const label = this.overview?.label ?? 'neutral';
    return `indicator--${label}`;
  }

  get indicatorText(): string {
    if (!this.overview) {
      return 'Loading…';
    }
    if (this.overview.label === 'positive') {
      return 'Positive day';
    }
    if (this.overview.label === 'negative') {
      return 'Negative day';
    }
    return 'Neutral day';
  }

  loadNews(showSpinner = false): void {
    if (showSpinner) {
      this.loading = true;
    }

    this.newsService.getOverview().subscribe({
      next: (overview) => {
        this.overview = overview;
        this.loading = false;
      },
      error: () => {
        this.loading = false;
      },
    });

    this.newsService.getArticles().subscribe({
      next: (articles) => {
        this.articles = articles;
        this.loading = false;
      },
      error: () => {
        this.loading = false;
      },
    });
  }

  refreshNow(): void {
    this.loadNews(true);
  }

  sentimentBadgeClass(article: NewsArticle): string {
    const score = article.sentiment_score;
    if (score >= 0.15) {
      return 'badge-positive';
    }
    if (score <= -0.15) {
      return 'badge-negative';
    }
    return 'badge-neutral';
  }

  sentimentLabel(article: NewsArticle): string {
    const score = article.sentiment_score;
    if (score >= 0.15) {
      return 'Positive';
    }
    if (score <= -0.15) {
      return 'Negative';
    }
    return 'Neutral';
  }

  formatCoins(article: NewsArticle): string {
    if (!article.coins.length) {
      return 'None';
    }
    return article.coins.join(', ');
  }

  truncate(value: string, max = 160): string {
    const text = (value || '').trim();
    if (text.length <= max) {
      return text;
    }
    return `${text.slice(0, max - 1).trimEnd()}…`;
  }
}
