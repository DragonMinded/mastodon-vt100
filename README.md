A Mastodon client that uses a VT-100 or compatible terminal to display. Assuming you have a VT-100 compatible terminal connected to your computer through a serial port, you can use this to interact with your home instance much the same way you would the web frontend or a mobile client.

To get started, first install the requirements using a command similar to:

```
python3 -m pip install -r requirements.txt
```

Then, you can run the application similar to:

```
python3 -m masto <your home instance here>
```

Note that you can run with help, like the following example, to see all options:

```
python3 -m masto --help
```

Note that original VT-100 terminals, and variants such as the 101 and 102, need the XON/XOFF flow control option enabled. Make sure you enable flow control on the terminal itself, and then use the `--flow` argument to avoid overloading the terminal. Newer terminals such as mid-80s VT-100 clones often do not suffer from this problem and keep up just fine.

Happy posting!
