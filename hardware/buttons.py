from gpiozero import Button

class DeviceButtons:
    def __init__(self, config, display, network, core):
        pins = config["button_pins"]
        self.power_btn = Button(pins["power"], hold_time=5)
        self.action_btn = Button(pins["action"], hold_time=1.5)
        self.interaction_btn = Button(pins["interaction"], hold_time=1.0)

        self.power_btn.when_pressed = display.refresh
        self.power_btn.when_held = core.graceful_shutdown
        self.action_btn.when_pressed = core.action_click_handler
        self.action_btn.when_held = network.cycle_state
        self.interaction_btn.when_pressed = core.cycle_agent
