/*
 * SPDX-FileCopyrightText: Copyright The Zephyr Project Contributors
 * SPDX-License-Identifier: Apache-2.0
 */

#include <zephyr/drivers/mfd/npm13xx.h>

static_assert(sizeof(npm13xx_event_t) == sizeof(uint32_t), "Event mask must be 32 bits");

static void handler(const struct device *dev, struct mfd_npm13xx_event_callback *cb,
		    npm13xx_event_t events)
{
	(void)dev;
	(void)cb;
	(void)events;
}

extern "C" int header_cpp_probe(const struct device *dev)
{
	struct mfd_npm13xx_event_callback callback = {};

	callback.handler = handler;
	callback.event_mask = 0U;
	int ret = mfd_npm13xx_add_callback(dev, &callback);

	return ret != 0 ? ret : mfd_npm13xx_remove_callback(dev, &callback);
}
