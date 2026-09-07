// בריכת בוטים עם רוטציה — בהשראת TG-FileStreamBot: כמה טוקנים, round-robin,
// כדי שגל של צופים חדשים לא כולם ידפקו על אותו חיבור באותה שנייה.
package main

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"sync"
	"sync/atomic"

	gotdlog "github.com/gotd/log"
	"github.com/gotd/log/logslog"
	"github.com/gotd/td/telegram"
	"github.com/gotd/td/tg"
)

// רמת INFO (לא DEBUG): לוגים ברמת דיבוג הציפו את stderr באלפי שורות לכל
// בקשה (כל chunk-ack נרשם), וזה יכול להאט משמעותית תחת עומס אמיתי.
var debugLogger gotdlog.Logger = logslog.New(slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelInfo})))

type botClient struct {
	name    string
	client  *telegram.Client
	api     *tg.Client
	channel tg.InputChannelClass // access_hash ספציפי לבוט הזה — לא ניתן לשיתוף בין בוטים
}

type Pool struct {
	apiID   int
	apiHash string
	bots    []*botClient
	idx     uint64 // round-robin counter, נגיש אטומית
	mu      sync.RWMutex
}

// NewPool בונה בריכה מרשימת טוקני בוטים. כל בוט מתחבר ומתאמת בנפרד
// (כמו start_download_workers בפייתון: אחד-אחד, לא בבת אחת — טלגרם דוחה
// כמה התחברויות בו-זמנית עם אותו IP).
//
// channelID ומספר ה-access_hash-ים חייבים להתאים אחד-לאחד לרשימת הטוקנים:
// access_hash הוא ספציפי לחשבון שמבקש אותו (נמדד בפועל — hash שהתקבל מבוט
// אחד גורם ל-CHANNEL_INVALID כשבוט אחר מנסה להשתמש בו), לכן כל בוט מקבל
// את שלו, לא ערך גלובלי משותף.
func NewPool(ctx context.Context, apiID int, apiHash string, tokens []string, channelID int64, accessHashes []int64) (*Pool, error) {
	if len(accessHashes) != len(tokens) {
		return nil, fmt.Errorf("מספר ה-access_hash-ים (%d) לא תואם למספר הטוקנים (%d)",
			len(accessHashes), len(tokens))
	}
	p := &Pool{apiID: apiID, apiHash: apiHash}
	for i, tok := range tokens {
		name := fmt.Sprintf("bot_%d", i)
		c := telegram.NewClient(apiID, apiHash, telegram.Options{Logger: debugLogger})
		bc := &botClient{
			name:    name,
			client:  c,
			channel: &tg.InputChannel{ChannelID: channelID, AccessHash: accessHashes[i]},
		}
		if err := connectAndAuth(ctx, bc, tok); err != nil {
			return nil, fmt.Errorf("בוט %s נכשל: %w", name, err)
		}
		p.bots = append(p.bots, bc)
	}
	if len(p.bots) == 0 {
		return nil, fmt.Errorf("לא הוגדר אף טוקן בוט")
	}
	return p, nil
}

// connectAndAuth מריץ את הלקוח ברקע (gotd/td דורש client.Run פעיל לאורך כל
// חיי החיבור) ומאמת עם טוקן הבוט. ה-tg.Client (ה-RPC) נשמר לשימוש חוזר.
func connectAndAuth(ctx context.Context, bc *botClient, token string) error {
	ready := make(chan error, 1)
	go func() {
		err := bc.client.Run(ctx, func(runCtx context.Context) error {
			if _, err := bc.client.Auth().Bot(runCtx, token); err != nil {
				ready <- err
				return err
			}
			bc.api = bc.client.API()
			ready <- nil
			<-runCtx.Done() // מחזיק את החיבור פתוח כל עוד ה-pool חי
			return nil
		})
		if err != nil {
			select {
			case ready <- err:
			default:
			}
		}
	}()
	return <-ready
}

// Next בוחר את הבוט הבא ברוטציה — קריאה זולה, בלי נעילה כבדה.
func (p *Pool) Next() *botClient {
	p.mu.RLock()
	defer p.mu.RUnlock()
	n := atomic.AddUint64(&p.idx, 1)
	return p.bots[n%uint64(len(p.bots))]
}

func (p *Pool) Len() int {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return len(p.bots)
}
