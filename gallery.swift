import AppKit
import Foundation

private let supportedExtensions: Set<String> = [
	"jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "heic", "avif"
]

struct GalleryItem {
	let url: URL
}

final class GalleryItemView: NSCollectionViewItem {
	override func loadView() {
		view = NSView()
	}

	override func viewDidLoad() {
		super.viewDidLoad()

		let imageView = NSImageView()
		imageView.translatesAutoresizingMaskIntoConstraints = false
		imageView.imageScaling = .scaleProportionallyUpOrDown
		imageView.wantsLayer = true
		imageView.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
		imageView.layer?.cornerRadius = 10
		imageView.layer?.masksToBounds = true
		self.imageView = imageView

		let textField = NSTextField(labelWithString: "")
		textField.translatesAutoresizingMaskIntoConstraints = false
		textField.alignment = .center
		textField.lineBreakMode = .byTruncatingMiddle
		textField.font = .systemFont(ofSize: 11, weight: .medium)
		textField.textColor = .secondaryLabelColor
		self.textField = textField

		view.addSubview(imageView)
		view.addSubview(textField)

		NSLayoutConstraint.activate([
			imageView.topAnchor.constraint(equalTo: view.topAnchor),
			imageView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
			imageView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
			imageView.heightAnchor.constraint(equalToConstant: 150),

			textField.topAnchor.constraint(equalTo: imageView.bottomAnchor, constant: 8),
			textField.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 4),
			textField.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -4),
			textField.bottomAnchor.constraint(lessThanOrEqualTo: view.bottomAnchor)
		])
	}
}

final class GalleryViewController: NSViewController, NSCollectionViewDataSource, NSCollectionViewDelegate {
	private let items: [GalleryItem]
	private let startIndex: Int
	private let collectionView = NSCollectionView()

	init(items: [GalleryItem], startIndex: Int) {
		self.items = items
		self.startIndex = startIndex
		super.init(nibName: nil, bundle: nil)
	}

	required init?(coder: NSCoder) {
		fatalError("init(coder:) has not been implemented")
	}

	override func loadView() {
		view = NSView()
	}

	override func viewDidLoad() {
		super.viewDidLoad()

		let layout = NSCollectionViewFlowLayout()
		layout.itemSize = NSSize(width: 180, height: 180)
		layout.minimumInteritemSpacing = 16
		layout.minimumLineSpacing = 16
		layout.sectionInset = NSEdgeInsets(top: 20, left: 20, bottom: 20, right: 20)

		collectionView.collectionViewLayout = layout
		collectionView.isSelectable = true
		collectionView.dataSource = self
		collectionView.delegate = self
		collectionView.register(GalleryItemView.self, forItemWithIdentifier: NSUserInterfaceItemIdentifier("GalleryItem"))
		collectionView.backgroundColors = [.windowBackgroundColor]

		let scrollView = NSScrollView()
		scrollView.translatesAutoresizingMaskIntoConstraints = false
		scrollView.hasVerticalScroller = true
		scrollView.autohidesScrollers = true
		scrollView.drawsBackground = false
		scrollView.documentView = collectionView

		view.addSubview(scrollView)
		NSLayoutConstraint.activate([
			scrollView.topAnchor.constraint(equalTo: view.topAnchor),
			scrollView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
			scrollView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
			scrollView.bottomAnchor.constraint(equalTo: view.bottomAnchor)
		])
	}

	override func viewDidAppear() {
		super.viewDidAppear()
		guard !items.isEmpty else { return }
		let index = max(0, min(startIndex, items.count - 1))
		let path = IndexPath(item: index, section: 0)
		collectionView.scrollToItems(at: Set([path]), scrollPosition: .centeredVertically)
		collectionView.selectionIndexPaths = Set([path])
	}

	func collectionView(_ collectionView: NSCollectionView, numberOfItemsInSection section: Int) -> Int {
		items.count
	}

	func collectionView(_ collectionView: NSCollectionView, itemForRepresentedObjectAt indexPath: IndexPath) -> NSCollectionViewItem {
		let item = collectionView.makeItem(withIdentifier: NSUserInterfaceItemIdentifier("GalleryItem"), for: indexPath)
		guard let galleryItem = item as? GalleryItemView else { return item }

		let data = items[indexPath.item]
		galleryItem.textField?.stringValue = data.url.lastPathComponent
		galleryItem.imageView?.image = NSImage(contentsOf: data.url)
		return galleryItem
	}
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
	private let items: [GalleryItem]
	private let startIndex: Int
	private let folderName: String
	private var window: NSWindow?

	init(items: [GalleryItem], startIndex: Int, folderName: String) {
		self.items = items
		self.startIndex = startIndex
		self.folderName = folderName
	}

	func applicationDidFinishLaunching(_ notification: Notification) {
		let controller = GalleryViewController(items: items, startIndex: startIndex)
		let window = NSWindow(
			contentRect: NSRect(x: 0, y: 0, width: 1180, height: 820),
			styleMask: [.titled, .closable, .miniaturizable, .resizable],
			backing: .buffered,
			defer: false
		)
		window.title = "\(folderName) (\(items.count) images)"
		window.center()
		window.contentViewController = controller
		window.delegate = self
		window.makeKeyAndOrderFront(nil)
		window.setFrameAutosaveName("GalleryWindow")

		self.window = window
		NSApp.activate(ignoringOtherApps: true)
	}

	func windowWillClose(_ notification: Notification) {
		NSApp.terminate(nil)
	}

	func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
		true
	}
}

func collectImages(in directoryURL: URL) -> [URL] {
	let options: FileManager.DirectoryEnumerationOptions = [.skipsHiddenFiles, .skipsSubdirectoryDescendants]
	guard let enumerator = FileManager.default.enumerator(at: directoryURL, includingPropertiesForKeys: [.isRegularFileKey], options: options) else {
		return []
	}

	var urls: [URL] = []
	for case let url as URL in enumerator {
		let ext = url.pathExtension.lowercased()
		guard supportedExtensions.contains(ext) else { continue }
		urls.append(url)
	}

	return urls.sorted {
		$0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending
	}
}

let args = CommandLine.arguments
let directoryPath = args.count > 1 ? args[1] : ""
let startImagePath = args.count > 2 ? args[2] : ""

let directoryURL = URL(fileURLWithPath: directoryPath)
let images = collectImages(in: directoryURL)

guard !images.isEmpty else {
	exit(0)
}

let startIndex: Int
if !startImagePath.isEmpty, let matched = images.firstIndex(where: { $0.path == startImagePath }) {
	startIndex = matched
} else {
	startIndex = 0
}

let items = images.map { GalleryItem(url: $0) }
let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = AppDelegate(items: items, startIndex: startIndex, folderName: directoryURL.lastPathComponent)
app.delegate = delegate
app.run()
