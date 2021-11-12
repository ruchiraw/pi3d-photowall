
# Bulk rename files
```sh
index=0; for name in *; do mv "$name" "photo-${index}.jpeg"; index=$((index+1)); done
```

# Setup in RPi 3
```
mkdir ~/.config/systemd/user/ -p && cp photowall.service ~/.config/systemd/user/photowall.service
sudo chmod 644 ~/.config/systemd/user/photowall.service
systemctl --user daemon-reload
systemctl --user enable photowall.service
```

## Managing the service
```
systemctl --user stop photowall.service
systemctl --user start photowall.service
systemctl --user restart photowall.service
```