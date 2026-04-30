package main

import (
	"fmt"
	"math/rand"
)

const (
	CurrentUser          = "li.wei"
	LocalTestSSHIP       = "192.168.1.15"
	LocalTestSSHUser     = "lon"
	LocalTestSSHPassword = "202188"
)

const (
	StatusIdle     = "空闲"
	StatusOccupied = "已被占用"
	StatusPipeline = "流水线占用"
	StatusOther    = "其他"
)

var (
	cpuModels = []string{
		"hi1213", "hi1215", "hi1260", "hi1280", "hi1382",
		"hi1383", "hi1620", "hi1620s", "ls1043", "ls1046",
	}
	domains = []string{"RTN", "XTN", "交企", "路由器", "测试"}
	deviceTypes = map[string][]string{
		"RTN":   {"Microwave", "Backhaul Node", "Aggregation Hop"},
		"XTN":   {"Transport Node", "OTN Shelf", "Metro Edge"},
		"交企":    {"Access Gateway", "Security Gateway", "Enterprise Edge"},
		"路由器":   {"Core Router", "PE Router", "Aggregation Router"},
		"测试":    {"Lab Device", "Validation Node", "Local SSH"},
	}
	statuses = []string{StatusIdle, StatusOccupied, StatusPipeline, StatusOther}
	vendors  = []string{"Huawei", "H3C", "Cisco", "Juniper", "Nokia", "ZTE"}
	sites    = []siteInfo{
		{Code: "BJ", Name: "Beijing Tongzhou"},
		{Code: "SH", Name: "Shanghai Pudong"},
		{Code: "GZ", Name: "Guangzhou Tianhe"},
		{Code: "SZ", Name: "Shenzhen Nanshan"},
		{Code: "CD", Name: "Chengdu Hi-Tech"},
		{Code: "WH", Name: "Wuhan Optics Valley"},
		{Code: "XA", Name: "Xi'an Software Park"},
		{Code: "HZ", Name: "Hangzhou Binjiang"},
	}
	ownerPool = []string{CurrentUser, "pipeline.bot", "wang.hao", "zhao.min", "ops.noc"}
	versionPool = []string{
		"V100R018C00",
		"V100R019C10",
		"V100R021C00",
		"R7608P30",
		"IOS-XE 17.09",
		"Junos 22.4R1",
	}
)

type siteInfo struct {
	Code string
	Name string
}

type Device struct {
	ID         string
	Name       string
	Domain     string
	DeviceType string
	CPU        string
	Status     string
	Owner      string
	SSHIP      string
	TelnetIP   string
	Username   string
	Password   string
	Vendor     string
	Model      string
	Site       string
	Rack       string
	Version    string
	Notes      string
}

func sampleDevices() []Device {
	base := []Device{
		{
			ID:         "LOCAL-SSH-001",
			Name:       "本机测试设备",
			Domain:     "测试",
			DeviceType: "Local SSH",
			CPU:        "hi1213",
			Status:     StatusIdle,
			SSHIP:      LocalTestSSHIP,
			TelnetIP:   "127.0.0.1",
			Username:   LocalTestSSHUser,
			Password:   LocalTestSSHPassword,
			Vendor:     "Microsoft OpenSSH",
			Model:      "Windows Localhost",
			Site:       "Local Machine",
			Rack:       "N/A",
			Version:    "OpenSSH_for_Windows_9.5p2",
			Notes:      "Dedicated local SSH test device.",
		},
		{
			ID:         "RTN-BJ-001",
			Name:       "RTN-950A-BJ01",
			Domain:     "RTN",
			DeviceType: "Microwave",
			CPU:        "hi1213",
			Status:     StatusOccupied,
			Owner:      "wang.hao",
			SSHIP:      LocalTestSSHIP,
			TelnetIP:   "172.16.1.11",
			Username:   LocalTestSSHUser,
			Password:   LocalTestSSHPassword,
			Vendor:     "Huawei",
			Model:      "RTN 950A",
			Site:       "Beijing Tongzhou",
			Rack:       "A01-U08",
			Version:    "V100R019C10",
			Notes:      "Backhaul node for aggregation ring.",
		},
		{
			ID:         "JQ-SH-003",
			Name:       "JQ-Access-SH03",
			Domain:     "交企",
			DeviceType: "Access Gateway",
			CPU:        "hi1215",
			Status:     StatusIdle,
			SSHIP:      LocalTestSSHIP,
			TelnetIP:   "172.20.3.21",
			Username:   LocalTestSSHUser,
			Password:   LocalTestSSHPassword,
			Vendor:     "H3C",
			Model:      "SecPath F1000",
			Site:       "Shanghai Pudong",
			Rack:       "B12-U16",
			Version:    "R7608P30",
			Notes:      "Traffic enterprise edge gateway.",
		},
		{
			ID:         "RTR-GZ-006",
			Name:       "Core-Router-GZ06",
			Domain:     "路由器",
			DeviceType: "Core Router",
			CPU:        "hi1260",
			Status:     StatusPipeline,
			Owner:      "pipeline.bot",
			SSHIP:      LocalTestSSHIP,
			TelnetIP:   "172.30.6.1",
			Username:   LocalTestSSHUser,
			Password:   LocalTestSSHPassword,
			Vendor:     "Cisco",
			Model:      "ASR 1006-X",
			Site:       "Guangzhou Tianhe",
			Rack:       "C03-U20",
			Version:    "IOS-XE 17.09",
			Notes:      "Reserved by validation job.",
		},
		{
			ID:         "XTN-CD-002",
			Name:       "XTN-Node-CD02",
			Domain:     "XTN",
			DeviceType: "Transport Node",
			CPU:        "hi1215",
			Status:     StatusIdle,
			SSHIP:      LocalTestSSHIP,
			TelnetIP:   "172.40.2.18",
			Username:   LocalTestSSHUser,
			Password:   LocalTestSSHPassword,
			Vendor:     "Huawei",
			Model:      "OptiXtrans XTN 980",
			Site:       "Chengdu Hi-Tech",
			Rack:       "D07-U11",
			Version:    "V100R021C00",
			Notes:      "Metro transport node with spare capacity.",
		},
		{
			ID:         "RTN-SZ-009",
			Name:       "RTN-Hop-SZ09",
			Domain:     "RTN",
			DeviceType: "Microwave",
			CPU:        "hi1213",
			Status:     StatusOther,
			Owner:      "ops.noc",
			SSHIP:      LocalTestSSHIP,
			TelnetIP:   "172.16.9.9",
			Username:   LocalTestSSHUser,
			Password:   LocalTestSSHPassword,
			Vendor:     "Huawei",
			Model:      "RTN 980",
			Site:       "Shenzhen Nanshan",
			Rack:       "E02-U05",
			Version:    "V100R018C00",
			Notes:      "Held for field handoff.",
		},
	}

	return append(base, generatedDevices(1000)...)
}

func generatedDevices(count int) []Device {
	rng := rand.New(rand.NewSource(20260430))
	devices := make([]Device, 0, count)
	domainCodes := map[string]string{
		"RTN": "RTN",
		"XTN": "XTN",
		"交企":  "JQ",
		"路由器": "RTR",
		"测试":  "TST",
	}

	for index := 1; index <= count; index++ {
		domain := domains[rng.Intn(len(domains))]
		site := sites[rng.Intn(len(sites))]
		deviceType := deviceTypes[domain][rng.Intn(len(deviceTypes[domain]))]
		cpu := cpuModels[rng.Intn(len(cpuModels))]
		status := weightedStatus(rng)
		owner := generatedOwner(status, rng)
		vendor := vendors[rng.Intn(len(vendors))]
		family := domainCodes[domain]
		serial := fmt.Sprintf("%04d", index)

		model, name := generatedIdentity(domain, family, site.Code, serial, rng)
		deviceID := fmt.Sprintf("%s-%s-%s", family, site.Code, serial)
		sshIP := fmt.Sprintf("10.%d.%d.%d", randomRange(rng, 10, 99), randomRange(rng, 0, 255), randomRange(rng, 1, 254))
		telnetIP := fmt.Sprintf("172.%d.%d.%d", randomRange(rng, 16, 31), randomRange(rng, 0, 255), randomRange(rng, 1, 254))
		rack := fmt.Sprintf("%c%02d-U%02d", rune('A'+rng.Intn(8)), randomRange(rng, 1, 24), randomRange(rng, 1, 24))
		version := versionPool[rng.Intn(len(versionPool))]
		notes := fmt.Sprintf("%s in %s. Generated sample record %s.", deviceType, site.Name, serial)

		devices = append(devices, Device{
			ID:         deviceID,
			Name:       name,
			Domain:     domain,
			DeviceType: deviceType,
			CPU:        cpu,
			Status:     status,
			Owner:      owner,
			SSHIP:      sshIP,
			TelnetIP:   telnetIP,
			Username:   LocalTestSSHUser,
			Password:   LocalTestSSHPassword,
			Vendor:     vendor,
			Model:      model,
			Site:       site.Name,
			Rack:       rack,
			Version:    version,
			Notes:      notes,
		})
	}

	return devices
}

func weightedStatus(rng *rand.Rand) string {
	roll := rng.Intn(100)
	switch {
	case roll < 55:
		return StatusIdle
	case roll < 77:
		return StatusOccupied
	case roll < 90:
		return StatusPipeline
	default:
		return StatusOther
	}
}

func generatedOwner(status string, rng *rand.Rand) string {
	switch status {
	case StatusIdle:
		return ""
	case StatusOccupied:
		for {
			owner := ownerPool[rng.Intn(len(ownerPool))]
			if owner != CurrentUser {
				return owner
			}
		}
	case StatusPipeline:
		return "pipeline.bot"
	default:
		if rng.Intn(2) == 0 {
			return "wang.hao"
		}
		return "ops.noc"
	}
}

func generatedIdentity(domain, family, areaCode, serial string, rng *rand.Rand) (string, string) {
	switch domain {
	case "RTN":
		models := []string{"RTN 905", "RTN 950A", "RTN 980"}
		return models[rng.Intn(len(models))], fmt.Sprintf("%s-Hop-%s%s", family, areaCode, serial)
	case "XTN":
		models := []string{"OptiXtrans XTN 960", "OptiXtrans XTN 980", "OSN 1800"}
		return models[rng.Intn(len(models))], fmt.Sprintf("%s-Node-%s%s", family, areaCode, serial)
	case "交企":
		models := []string{"SecPath F1000", "SecPath F5000", "NE8000 M1A"}
		return models[rng.Intn(len(models))], fmt.Sprintf("%s-Access-%s%s", family, areaCode, serial)
	case "路由器":
		models := []string{"ASR 1006-X", "NE40E-X8A", "MX480"}
		return models[rng.Intn(len(models))], fmt.Sprintf("%s-Core-%s%s", family, areaCode, serial)
	default:
		models := []string{"Lab VM", "Localhost SSH", "Validation Host"}
		return models[rng.Intn(len(models))], fmt.Sprintf("%s-Lab-%s%s", family, areaCode, serial)
	}
}

func randomRange(rng *rand.Rand, min, max int) int {
	return min + rng.Intn(max-min+1)
}
