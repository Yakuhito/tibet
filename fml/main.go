package main

import (
	"github.com/gofiber/fiber/v2"
	"github.com/goccy/go-json"
	"golang.org/x/sync/singleflight"
	"io/ioutil"
	"log"
	"net/http"
	"sync"
	"time"
)

type Coin struct {
	Amount uint64 `json:"amount"`
	ParentCoinInfo string `json:"parent_coin_info"`
	PuzzleHash string `json:"puzzle_hash"`
}

type CoinSpend struct {
	Coin Coin `json:"coin"`
	PuzzleReveal string `json:"puzzle_reveal"`
	Solution string `json:"solution"`
}

type SpendBundle struct {
	AggregatedSignature string `json:"aggregated_signature"`
	CoinSpends []CoinSpend `json:"coin_spends"`
}

type MempoolItem struct {
	SpendBundle SpendBundle `json:"spend_bundle"`
}

type AllMempoolItemsResponse struct {
	Success bool `json:"success"`
	MempoolItems map[string]MempoolItem `json:"mempool_items"`
}

type GetMempoolItemByParentCoinInfoArgs struct {
    ParentCoinInfo string `json:"parent_coin_info"`
	RequestURL string `json:"request_url"`
}

type CacheItem struct {
	Response *AllMempoolItemsResponse
	Expiry   time.Time
}

type Cache struct {
	mu          sync.Mutex
	items       map[string]*CacheItem
	fetchGroup  singleflight.Group
}

var cache = &Cache{
	items: make(map[string]*CacheItem),
}

func GetAllMempoolItemsResponse(request_url string) (AllMempoolItemsResponse, error) {
	res, err := http.Get(request_url)
	if err != nil {
		return AllMempoolItemsResponse{}, err
	}
	defer res.Body.Close()

	resBody, err := ioutil.ReadAll(res.Body)
	if err != nil {
		return AllMempoolItemsResponse{}, err
	}

	var resp AllMempoolItemsResponse
	err = json.Unmarshal(resBody, &resp)
	if err != nil {
		return AllMempoolItemsResponse{}, err
	}

	return resp, nil
}

func (c *Cache) FetchAndUpdateCache(key string) (*AllMempoolItemsResponse, error) {
	resp, err, _ := c.fetchGroup.Do(key, func() (interface{}, error) {
		response, err := GetAllMempoolItemsResponse(key)
		if err != nil {
			return nil, err
		}
		c.Set(key, &response, 5*time.Second)
		return &response, nil
	})

	if err != nil {
		return nil, err
	}
	return resp.(*AllMempoolItemsResponse), nil
}

func (c *Cache) Set(key string, value *AllMempoolItemsResponse, duration time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()

	c.items[key] = &CacheItem{
		Response: value,
		Expiry:   time.Now().Add(duration),
	}
}

func (c *Cache) Get(key string) (*AllMempoolItemsResponse, bool) {
	c.mu.Lock()
	item, found := c.items[key]
	c.mu.Unlock()

	if found && time.Now().After(item.Expiry) {
		go func() {
			if _, err := c.FetchAndUpdateCache(key); err != nil {
				log.Printf("Error updating cache for key '%s': %v", key, err)
			}
		}()
	}

	return item.Response, found
}

func GetMempoolItemByParentCoinInfo(c *fiber.Ctx) error {
	args := new(GetMempoolItemByParentCoinInfoArgs)

	if err := c.BodyParser(args); err != nil {
		return err
	}

	cachedResponse, found := cache.Get(args.RequestURL)
	if !found {
		resp, err := GetAllMempoolItemsResponse(args.RequestURL)
		if err != nil {
			return c.JSON(fiber.Map{
				"item": nil,
			})
		}

		cache.Set(args.RequestURL, &resp, 5 * time.Second)
		cachedResponse = &resp
	}

	if !cachedResponse.Success {
		return c.JSON(fiber.Map{
			"item": nil,
		})
	}

	var item SpendBundle
	found = false

	for _, v := range cachedResponse.MempoolItems {
		for _, cs := range v.SpendBundle.CoinSpends {
			if cs.Coin.ParentCoinInfo == args.ParentCoinInfo {
				found = true
				item = v.SpendBundle
				break
			}
		}

		if found {
			break
		}
	}

	if !found {
		return c.JSON(fiber.Map{
			"item": nil,
		})
	}

	return c.JSON(fiber.Map{
		"item": item,
	})
}

func main() {
    app := fiber.New(fiber.Config{
        JSONEncoder: json.Marshal,
        JSONDecoder: json.Unmarshal,
    })

    app.Get("/", func(c *fiber.Ctx) error {
        return c.SendString("Fast Mempool Locator is running! ~ FML")
    })
	app.Post("/get_mempool_item_by_parent_coin_info", GetMempoolItemByParentCoinInfo)

    app.Listen(":1337")
}