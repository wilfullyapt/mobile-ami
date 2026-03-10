from gpiozero import Button


class DeviceButtons:
    """
    Wires the three physical buttons to their respective handlers.

    Machine button (GPIO 17):
      press  → display.toggle()           screen on/off; resets 15 s timeout
      hold   → core.graceful_shutdown()   5 s hold → power off

    Action button (GPIO 27):
      press  → core.trigger_listening()   always triggers a manual listen cycle
                                          (works in all three interaction modes)
      hold   → core.cycle_mode()          1.5 s hold → cycle interaction mode:
                                           manual → hot_word → ally → manual

    Interaction button (GPIO 22):
      press  → core.cycle_agent()         advance to next AI agent
      hold   → network.cycle_state()      1.5 s hold → cycle offline/hotspot/wifi
    """

    def __init__(self, config, display, network, core):
        pins = config["button_pins"]
        self.machine_btn = Button(pins["power"], hold_time=5)
        self.action_btn = Button(pins["action"], hold_time=1.5)
        self.interaction_btn = Button(pins["interaction"], hold_time=1.5)

        self.machine_btn.when_pressed = display.toggle
        self.machine_btn.when_held = core.graceful_shutdown

        self.action_btn.when_pressed = core.trigger_listening
        self.action_btn.when_held = core.cycle_mode

        self.interaction_btn.when_pressed = core.cycle_agent
        self.interaction_btn.when_held = network.cycle_state
