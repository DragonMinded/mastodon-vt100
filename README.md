# mastodon-vt100

A Mastodon client that uses a VT-100 or compatible terminal to display. Assuming you have a VT-100 compatible terminal connected to your computer through a serial port, you can use this to interact with your home instance much the same way you would the web frontend or a mobile client.

## Running This

If you are non-technical, or you just want to try it out without tinkering, I recommend using `pipx` to install the client. For help and instruction on setting up `pipx` on your computer, visit [pipx's installation page](https://pipx.pypa.io/stable/installation/). If you have `pipx` installed already, run the following line to install the mastodon-vt100 client on your computer.

```
pipx install git+https://github.com/DragonMinded/mastodon-vt100
```

Once that completes, you can run this client by typing the following line, substituting your instance:

```
mastodon-vt100 <your home instance here>
```

You can also run with `--help`, like the following example, to see all options:

```
mastodon-vt100 --help
```

Note that original VT-100 terminals, and variants such as the 101 and 102, need the XON/XOFF flow control option enabled. Make sure you enable flow control on the terminal itself, and then use the `--flow` argument to avoid overloading the terminal. Newer terminals such as mid-80s VT-100 clones often do not suffer from this problem and keep up just fine.

Happy posting!

## Development

To get started, first install the requirements using a command similar to:

```
python3 -m pip install -r requirements.txt
python3 -m pip install -r requirements-dev.txt
```

Then, you can run the application similar to:

```
python3 -m masto <your home instance here>
```

You can also run with `--help`, like the following example, to see all options:

```
python3 -m masto --help
```
